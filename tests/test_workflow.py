import contextlib
import importlib.util
import io
from pathlib import Path
import subprocess
import tarfile
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


workflow = load("workflow", ROOT / "workflow.py")
deploy = load("deploy", ROOT / "deploy.py")
export_chat = load("export_chat", ROOT / "tools/export_chat.py")
RUN = subprocess.run


def git(folder, *args):
    return RUN(["git", *args], cwd=folder, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True).stdout.strip()


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)
        self.origin = self.folder / "origin.git"
        self.local = self.folder / "local"
        self.other = self.folder / "other"
        git(self.folder, "init", "--bare", "--initial-branch=main", str(self.origin))
        git(self.folder, "clone", str(self.origin), str(self.local))
        self.identity(self.local)
        (self.local / "file.txt").write_text("initial", encoding="utf-8")
        git(self.local, "add", "file.txt")
        git(self.local, "commit", "-m", "initial")
        git(self.local, "push", "-u", "origin", "main")
        git(self.folder, "clone", str(self.origin), str(self.other))
        self.identity(self.other)
        self.patch = patch.object(workflow, "ROOT", self.local)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def identity(self, folder):
        git(folder, "config", "user.name", "Workflow Test")
        git(folder, "config", "user.email", "workflow@example.invalid")

    def remote_update(self):
        (self.other / "remote.txt").write_text("remote", encoding="utf-8")
        git(self.other, "add", "remote.txt")
        git(self.other, "commit", "-m", "remote update")
        git(self.other, "push")

    def test_prepare_fast_forward(self):
        self.remote_update()
        original = git(self.local, "rev-parse", "HEAD")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            workflow.prepare()
        self.assertEqual(git(self.local, "rev-parse", "HEAD"), git(self.other, "rev-parse", "HEAD"))
        text = output.getvalue()
        self.assertIn(f"{original[:12]} -> {git(self.other, 'rev-parse', 'HEAD')[:12]}", text)
        self.assertIn("remote update", text)
        self.assertIn("A\tremote.txt", text)
        self.assertIn("1 insertion", text)
        self.assertLess(text.index("[拉取前 Diff]"), text.index("[3/5 完成]"))
        self.assertGreater(text.index("[拉取后 Diff]"), text.index("[3/5 完成]"))

    def test_prepare_without_remote_updates_reports_no_pull_diff(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            workflow.prepare()
        self.assertIn("无远端新增提交，未拉取文件", output.getvalue())
        self.assertNotIn("[拉取后 Diff]", output.getvalue())

    def test_prepare_preserves_dirty_files_when_behind(self):
        (self.local / "file.txt").write_text("local edit", encoding="utf-8")
        original = git(self.local, "rev-parse", "HEAD")
        self.remote_update()
        output = io.StringIO()
        with contextlib.redirect_stdout(output), self.assertRaisesRegex(RuntimeError, "未提交修改"):
            workflow.prepare()
        self.assertEqual(git(self.local, "rev-parse", "HEAD"), original)
        self.assertEqual((self.local / "file.txt").read_text(), "local edit")
        self.assertIn("[拉取前 Diff]", output.getvalue())
        self.assertNotIn("[拉取后 Diff]", output.getvalue())

    def test_prepare_refuses_diverged_history(self):
        (self.local / "file.txt").write_text("local", encoding="utf-8")
        git(self.local, "commit", "-am", "local update")
        self.remote_update()
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(RuntimeError, "分叉"):
            workflow.prepare()

    def test_release_stops_when_remote_changed_during_development(self):
        self.remote_update()
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(RuntimeError, "开发期间"):
            workflow.release("release", ["file.txt"])
        self.assertEqual(git(self.local, "status", "--porcelain"), "")

    def test_release_pushes_before_deploy_and_leaves_unrelated_files(self):
        (self.local / "file.txt").write_text("release", encoding="utf-8")
        (self.local / "unrelated.txt").write_text("not part of release", encoding="utf-8")
        deployed = []

        def run(command, **kwargs):
            if len(command) > 1 and command[1] == str(self.local / "deploy.py"):
                revision = command[-1]
                self.assertEqual(git(self.origin, "rev-parse", "main"), revision)
                self.assertNotIn("unrelated.txt", git(self.local, "ls-tree", "--name-only", revision))
                deployed.append(revision)
                return types.SimpleNamespace(returncode=0)
            return RUN(command, **kwargs)

        with patch.object(workflow.subprocess, "run", side_effect=run), contextlib.redirect_stdout(io.StringIO()):
            workflow.release("release", ["file.txt"])
        self.assertEqual(deployed, [git(self.local, "rev-parse", "HEAD")])
        self.assertIn("unrelated.txt", git(self.local, "status", "--porcelain"))

    def test_failed_push_never_deploys(self):
        (self.local / "file.txt").write_text("release", encoding="utf-8")
        git(self.local, "remote", "set-url", "--push", "origin", str(self.folder / "missing.git"))
        calls = []

        def run(command, **kwargs):
            calls.append(command)
            return RUN(command, **kwargs)

        with patch.object(workflow.subprocess, "run", side_effect=run), contextlib.redirect_stdout(io.StringIO()), self.assertRaises(RuntimeError):
            workflow.release("release", ["file.txt"])
        self.assertFalse(any(len(command) > 1 and command[1] == str(self.local / "deploy.py") for command in calls))

    def test_deploy_reads_committed_files_and_excludes_ssh_password(self):
        for name in ("Dockerfile", ".dockerignore", "requirements.txt", "deploy.sh"):
            (self.local / name).write_text("fixture", encoding="utf-8")
        (self.local / "app").mkdir()
        (self.local / "app/main.py").write_text("committed-code", encoding="utf-8")
        git(self.local, "add", ".")
        git(self.local, "commit", "-m", "deployment fixture")
        revision = git(self.local, "rev-parse", "HEAD")
        (self.local / "app/main.py").write_text("UNCOMMITTED-CODE", encoding="utf-8")
        config = dict(SSH_HOST="example.invalid", SSH_PASSWORD="ssh-secret", DB_PASSWORD="db-secret")
        paths = []

        def inspect(archive, config, command):
            paths.append(archive)
            with tarfile.open(archive) as bundle:
                self.assertEqual(bundle.extractfile("app/main.py").read(), b"committed-code")
                self.assertEqual(bundle.extractfile(".release-revision").read().decode().strip(), revision)
                self.assertEqual(bundle.getmember(".env.server").mode, 0o600)
                for member in bundle.getmembers():
                    data = bundle.extractfile(member).read()
                    self.assertNotIn(b"ssh-secret", data)
                    self.assertNotIn(b"UNCOMMITTED-CODE", data)
            return 0

        with patch.object(deploy, "ROOT", self.local), patch.object(deploy, "dotenv_values", return_value=config), patch.object(deploy, "deploy_with_password", side_effect=inspect), patch.object(deploy.shutil, "which", return_value="ssh"), contextlib.redirect_stdout(io.StringIO()):
            deploy.main(revision)
        self.assertFalse(paths[0].exists())


class ExportTests(unittest.TestCase):
    def test_redacts_and_excludes_internal_content(self):
        import json
        records = [
            {"type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "password=private-value"}]}},
            {"type": "response_item", "payload": {"type": "message", "role": "assistant", "phase": "analysis", "content": [{"type": "output_text", "text": "internal-analysis"}]}},
            {"type": "response_item", "payload": {"type": "function_call_output", "output": "private-value-tool-output"}},
            {"type": "response_item", "payload": {"type": "message", "role": "assistant", "phase": "final", "content": [{"type": "output_text", "text": "done"}]}},
            {"type": "response_item", "payload": {"type": "message", "role": "assistant", "phase": "final_answer", "content": [{"type": "output_text", "text": "desktop-final-answer"}]}},
        ]
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "source.jsonl"
            output = Path(folder) / "output.md"
            source.write_text("\n".join(json.dumps(record) for record in records), encoding="utf-8")
            with patch.object(export_chat, "secrets", return_value=["private-value"]), contextlib.redirect_stdout(io.StringIO()):
                export_chat.export(source, output)
            text = output.read_text(encoding="utf-8")
            self.assertIn("[已脱敏]", text)
            self.assertNotIn("private-value", text)
            self.assertNotIn("internal-analysis", text)
            self.assertNotIn("tool-output", text)
            self.assertIn("done", text)
            self.assertIn("desktop-final-answer", text)


if __name__ == "__main__":
    unittest.main()

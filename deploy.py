"""Deploy using SSH_PASSWORD from local .env, or interactive OpenSSH."""
import argparse
import os
from io import BytesIO
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile

from dotenv import dotenv_values


ROOT = Path(__file__).resolve().parent


def ssh_command(config, remote_command):
    return [
        "ssh", "-T", "-o", "ConnectTimeout=15", "-o", "ServerAliveInterval=30",
        "-p", config.get("SSH_PORT") or "22",
        f"{config.get('SSH_USER') or 'root'}@{config['SSH_HOST']}", remote_command,
    ]


def deploy_with_password(archive, config, remote_command):
    # Windows OpenSSH requires an executable askpass helper. Compile it with the
    # built-in .NET compiler; only the child process environment holds the password.
    compiler = Path(os.environ.get("SystemRoot", "C:/Windows")) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
    if not compiler.exists():
        raise SystemExit("Windows .NET Framework compiler is required for automatic SSH login.")
    # Cache this password-free helper outside the credentials archive directory.
    # Windows antivirus may briefly lock a newly executed .exe against deletion.
    helper_dir = ROOT.parent / "work" / "apiele-ssh-helper"
    helper_dir.mkdir(parents=True, exist_ok=True)
    helper = helper_dir / "ssh-askpass.exe"
    source = helper_dir / "ssh-askpass.cs"
    helper_source = (
        'class AskPass { static void Main() { System.Console.Write('
        'System.Environment.GetEnvironmentVariable("APIELE_SSH_PASSWORD")); } }'
    )
    if not helper.exists() or not source.exists() or source.read_text(encoding="utf-8") != helper_source:
        source.write_text(helper_source, encoding="utf-8")
        subprocess.run(
            [str(compiler), "/nologo", "/target:exe", f"/out:{helper}", str(source)],
            check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
    environment = os.environ.copy()
    environment.update(
        SSH_ASKPASS=str(helper), SSH_ASKPASS_REQUIRE="force", DISPLAY="apiele-deploy",
        APIELE_SSH_PASSWORD=config["SSH_PASSWORD"],
    )
    command = ssh_command(config, remote_command)
    command[1:1] = [
        "-o", "StrictHostKeyChecking=yes", "-o", "NumberOfPasswordPrompts=1",
        "-o", "PreferredAuthentications=password,keyboard-interactive",
        "-o", "PubkeyAuthentication=no",
    ]
    with archive.open("rb") as payload:
        return subprocess.run(command, stdin=payload, env=environment).returncode


def git_output(*arguments):
    return subprocess.run(
        ["git", *arguments], cwd=ROOT, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    ).stdout


def main(revision=None):
    if revision:
        revision = git_output("rev-parse", "--verify", f"{revision}^{{commit}}").decode().strip()
        print(f"[部署] 使用已提交版本 {revision[:12]}，从 Git 读取发布文件。", flush=True)
    config = dotenv_values(ROOT / ".env")
    for key in ("SSH_HOST", "DB_PASSWORD"):
        if not config.get(key):
            raise SystemExit(f"Fill {key} in the local .env file first.")
    if shutil.which("ssh") is None:
        raise SystemExit("OpenSSH client is required.")

    values = {
        "DB_HOST": "127.0.0.1",
        "DB_PORT": config.get("SSH_REMOTE_DB_PORT") or "3307",
        "DB_NAME": config.get("DB_NAME") or "apiele_test_dev",
        "DB_USER": config.get("DB_USER") or "apiele_dev",
        "DB_PASSWORD": config["DB_PASSWORD"],
    }
    if any("\n" in value or "\r" in value for value in values.values()):
        raise SystemExit("Database configuration must not contain newline characters.")
    server_env = "".join(f"{key}={value}\n" for key, value in values.items()).encode("utf-8")

    # The temporary archive includes credentials; never place it in outputs or Git.
    scratch = ROOT.parent / "work"
    scratch.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="apiele-deploy-", dir=scratch) as temporary:
        archive = Path(temporary) / "deployment.tar.gz"
        with tarfile.open(archive, "w:gz") as bundle:
            names = ["Dockerfile", ".dockerignore", "requirements.txt", "deploy.sh"]
            if revision:
                names = git_output("ls-tree", "-r", "--name-only", revision, "--", *names, "app").decode().splitlines()
            else:
                names.extend(path.relative_to(ROOT).as_posix() for path in (ROOT / "app").rglob("*") if path.is_file() and "__pycache__" not in path.parts)
            for name in names:
                # Convert text files to LF even when Git checks them out as CRLF.
                payload = (git_output("show", f"{revision}:{name}") if revision else (ROOT / name).read_bytes()).replace(b"\r\n", b"\n")
                entry = tarfile.TarInfo(name)
                entry.size = len(payload)
                entry.mode = 0o644
                bundle.addfile(entry, BytesIO(payload))
            entry = tarfile.TarInfo(".env.server")
            entry.size = len(server_env)
            entry.mode = 0o600
            bundle.addfile(entry, BytesIO(server_env))
            version = ((revision or "manual-unversioned") + "\n").encode()
            entry = tarfile.TarInfo(".release-revision")
            entry.size = len(version)
            entry.mode = 0o644
            bundle.addfile(entry, BytesIO(version))

        print("[部署完成步骤] 发布包已准备，SSH 密码未写入发布包。", flush=True)
        remote_command = "umask 077; mkdir -p /opt/apiele-test && tar -xzf - -C /opt/apiele-test && bash /opt/apiele-test/deploy.sh"
        command = ssh_command(config, remote_command)
        if config.get("SSH_PASSWORD"):
            print("Using SSH_PASSWORD from local .env.", flush=True)
            try:
                returncode = deploy_with_password(archive, config, remote_command)
            except Exception as error:
                raise SystemExit(f"SSH deployment failed ({type(error).__name__}). Check SSH credentials, known_hosts and server connectivity.") from None
        else:
            print("Enter your SERVER SSH login password when prompted. The MySQL password is transferred over SSH.", flush=True)
            with archive.open("rb") as source:
                returncode = subprocess.run(command, stdin=source).returncode
        if returncode:
            raise SystemExit(f"Deployment did not complete (SSH exit {returncode}). Keep the error output for troubleshooting.")
    print(f"Website: http://{config['SSH_HOST']}:8010/", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", help="从指定 Git 提交打包，协作发布由 workflow.py 传入")
    main(parser.parse_args().revision)

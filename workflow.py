"""Shared development/release commands. No extra dependencies required."""
import argparse
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent


def notice(message):
    print(message, flush=True)


def git(*arguments, capture=True):
    result = subprocess.run(
        ["git", *arguments], cwd=ROOT, text=True, encoding="utf-8", errors="replace",
        stdout=subprocess.PIPE if capture else None, stderr=subprocess.PIPE if capture else None,
    )
    if result.returncode:
        raise RuntimeError(f"git {' '.join(arguments[:2])} failed.\n{result.stderr or ''}")
    return result.stdout.strip() if capture else ""


def synchronize(allow_pull):
    branch = git("symbolic-ref", "--short", "HEAD")
    upstream = git("rev-parse", "--abbrev-ref", "@{upstream}")
    notice(f"[1/5 完成] 检测仓库：{branch}，本地版本 {git('rev-parse', '--short', 'HEAD')}。")
    git("-c", "credential.interactive=never", "fetch", "origin")
    ahead, behind = map(int, git("rev-list", "--left-right", "--count", f"HEAD...{upstream}").split())
    notice(f"[2/5 完成] 检查远端：本地领先 {ahead} 个提交，落后 {behind} 个提交。")
    if behind:
        if ahead:
            raise RuntimeError("本地与远端已分叉；停止，不自动合并、变基或覆盖代码。")
        before = git("rev-parse", "HEAD")
        target = git("rev-parse", upstream)
        notice(f"[拉取前 Diff] {before[:12]} -> {target[:12]}，远端新增提交：")
        notice(git("log", "--oneline", f"{before}..{target}"))
        notice("[Diff 文件] A=新增，M=修改，D=删除，R=重命名：")
        notice(git("-c", "core.quotePath=false", "diff", "--name-status", "--find-renames", before, target))
        notice("[Diff 行数] 各文件及总计：")
        notice(git("-c", "core.quotePath=false", "diff", "--stat", before, target))
        if not allow_pull:
            raise RuntimeError("远端在开发期间已更新；请先 prepare、检查更新并重新验证，再发布。")
        if git("status", "--porcelain"):
            raise RuntimeError("远端有更新，但本地存在未提交修改；保留修改并停止拉取，请先处理。")
        git("merge", "--ff-only", target)
        notice(f"[3/5 完成] 已快进拉取到 {git('rev-parse', '--short', 'HEAD')}。")
        notice(f"[拉取后 Diff] 已应用 {before[:12]} -> {target[:12]}；实际变更文件与增删行数见上方 Diff。")
    else:
        notice("[3/5 完成] 无远端更新，无需拉取。")
        notice("[Diff] 无远端新增提交，未拉取文件。")
    return branch, upstream


def prepare():
    synchronize(allow_pull=True)
    if git("status", "--porcelain"):
        notice("[提示] 已有本地修改；请先确认归属，保留与本次任务无关的修改。")
    notice("[4/5 待执行] 正常开发、更新会话记录，并完成与改动相关的检查。")
    notice("[5/5 等待] 开发完成后报告结果；仅收到明确发布指令才执行 release。")


def release(message, files):
    branch, upstream = synchronize(allow_pull=False)
    if branch != "main" or upstream != "origin/main":
        raise RuntimeError("发布只允许 main -> origin/main；请先将已检查的代码合入 main。")
    if git("diff", "--cached", "--name-only"):
        raise RuntimeError("暂存区已有修改；请确认归属并清空暂存区后，使用 --files 明确指定本次文件。")
    for name in files:
        path = Path(name)
        if path.is_absolute() or ".." in path.parts or name.startswith(":"):
            raise RuntimeError("--files 只接受仓库内的普通相对路径。")
        if (ROOT / path).is_dir():
            raise RuntimeError("--files 请逐个列出已审查文件，不接受整个目录。")
        if any(part in {".git", ".venv", "logs", "__pycache__"} for part in path.parts):
            raise RuntimeError("禁止将本机运行文件加入发布提交。")
        if any(part.startswith(".env") and part != ".env.example" for part in path.parts):
            raise RuntimeError("禁止提交真实环境配置。")
    git("--literal-pathspecs", "add", "--", *files)
    if git("diff", "--cached", "--name-only"):
        git("diff", "--cached", "--check")
        git("commit", "-m", message, capture=False)
        notice("[4/5 完成] 本次代码和协作记录已提交到本地 Git。")
    else:
        notice("[4/5 完成] 指定文件无新改动，将发布当前提交。")
    revision = git("rev-parse", "HEAD")
    git("-c", "credential.interactive=never", "push", "origin", "HEAD:refs/heads/main", capture=False)
    notice(f"[5/5 完成] GitHub 已推送版本 {revision[:12]}。")
    # Push failure raises above: never deploy a revision that collaborators cannot fetch.
    result = subprocess.run([sys.executable, str(ROOT / "deploy.py"), "--revision", revision], cwd=ROOT)
    if result.returncode:
        raise RuntimeError(f"GitHub 已推送 {revision[:12]}，服务器部署未确认成功；保留报错，勿重复提交。")
    notice(f"[发布完成] 服务器部署和数据库检查通过，版本 {revision[:12]}。")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("prepare", help="开发前检查远端，仅安全快进拉取")
    publish = commands.add_parser("release", help="明确发布后：指定文件提交 -> 推送 -> 部署同一版本")
    publish.add_argument("--message", required=True)
    publish.add_argument("--files", nargs="+", required=True)
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            prepare()
        else:
            release(args.message, args.files)
    except (RuntimeError, OSError) as error:
        notice(f"[已停止] {error}")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()

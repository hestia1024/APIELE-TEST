"""Upload and deploy through one interactive SSH connection. No password is stored."""
from io import BytesIO
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile

from dotenv import dotenv_values


ROOT = Path(__file__).resolve().parent


def main():
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
            paths = [ROOT / name for name in ("Dockerfile", ".dockerignore", "requirements.txt", "deploy.sh")]
            paths.extend(path for path in (ROOT / "app").rglob("*") if path.is_file() and "__pycache__" not in path.parts)
            for path in paths:
                # Convert text files to LF even when Git checks them out as CRLF.
                payload = path.read_bytes().replace(b"\r\n", b"\n")
                entry = tarfile.TarInfo(path.relative_to(ROOT).as_posix())
                entry.size = len(payload)
                entry.mode = 0o644
                bundle.addfile(entry, BytesIO(payload))
            entry = tarfile.TarInfo(".env.server")
            entry.size = len(server_env)
            entry.mode = 0o600
            bundle.addfile(entry, BytesIO(server_env))

        destination = f"{config.get('SSH_USER') or 'root'}@{config['SSH_HOST']}"
        command = [
            "ssh", "-T", "-o", "ConnectTimeout=15", "-o", "ServerAliveInterval=30",
            "-p", config.get("SSH_PORT") or "22", destination,
            "umask 077; mkdir -p /opt/apiele-test && tar -xzf - -C /opt/apiele-test && bash /opt/apiele-test/deploy.sh",
        ]
        print("Enter your SERVER SSH login password when prompted. The MySQL password is transferred over SSH.", flush=True)
        with archive.open("rb") as source:
            result = subprocess.run(command, stdin=source)
        if result.returncode:
            raise SystemExit(f"Deployment did not complete (SSH exit {result.returncode}). Keep the error output for troubleshooting.")
    print(f"Website: http://{config['SSH_HOST']}:8010/", flush=True)


if __name__ == "__main__":
    main()

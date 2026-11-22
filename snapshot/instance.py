"""Create, run and remove a throw-away local TCKDB instance, served by the pinned container image.

An instance is a database (``tckdb_test_snapshot_<name>``), a bucket (``tckdb-test-snapshot-<name>``) and an API
container (``tckdb-snapshot-<name>``) of the image ``pins.toml`` names, by digest, on a local port. ``down --drop``
refuses names without the ``tckdb_test_`` prefix.

    python snapshot/instance.py up --name a --port 8101
    python snapshot/instance.py down --name a [--drop]
    python snapshot/instance.py restore --name c --archive snapshot/tckdb.archive

Needs Docker, Postgres with the RDKit cartridge (``docker compose up -d db`` in ``tckdb/``) and an S3-compatible store
at ``S3_ENDPOINT_URL`` (default ``http://localhost:9000``, credentials ``S3_ACCESS_KEY`` / ``S3_SECRET_KEY``), both
reachable on the host's network. The migrations, the API, ``restore`` and the creation and removal of the database and
the bucket (``instance_admin.py``) run in the image, so the host needs only Docker and Python's standard library.
Process state and the API's log live under ``--work-dir``.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
import urllib.request
from pathlib import Path

import image

REPO_ROOT = Path(__file__).resolve().parents[1]


def container_name(name: str) -> str:
    return f"tckdb-snapshot-{name}"


def _db_env(name: str) -> dict[str, str]:
    """The database and object-store settings of instance ``name`` (what the API container is given)."""
    return dict(
        DB_USER=os.environ.get("DB_USER", "tckdb"),
        DB_PASSWORD=os.environ.get("DB_PASSWORD", "tckdb"),
        DB_HOST=os.environ.get("DB_HOST", "127.0.0.1"),
        DB_PORT=os.environ.get("DB_PORT", "5432"),
        DB_NAME=f"tckdb_test_snapshot_{name}",
        S3_BUCKET=f"tckdb-test-snapshot-{name}",
        S3_ENDPOINT_URL=os.environ.get("S3_ENDPOINT_URL", "http://localhost:9000"),
        S3_ACCESS_KEY=os.environ.get("S3_ACCESS_KEY", "tckdb"),
        S3_SECRET_KEY=os.environ.get("S3_SECRET_KEY", "tckdb_secret"),
        RATE_LIMIT_ENABLED="false",
    )


def up(name: str, port: int, work_dir: Path) -> None:
    env = _db_env(name)
    dbname = env["DB_NAME"]
    image.ensure_pulled()
    created = image.run(["python", "-m", "snapshot.instance_admin", "create"], env, check=False)
    if created.returncode != 0:
        raise SystemExit(f"could not create the database and bucket:\n{created.stdout}\n{created.stderr}")
    migrated = image.run(["alembic", "upgrade", "head"], env, check=False)
    if migrated.returncode != 0:
        raise SystemExit(f"alembic upgrade head failed in {image.IMAGE}:\n{migrated.stdout}\n{migrated.stderr}")
    work_dir.mkdir(parents=True, exist_ok=True)
    container = container_name(name)
    image.start(
        ["uvicorn", "app.api.app:create_app", "--factory", "--host", "127.0.0.1", "--port", str(port)], env, container
    )
    digest = image.container_image_digest(container)
    (work_dir / f"instance_{name}.json").write_text(
        json.dumps({"container": container, "port": port, "db": dbname, "image": image.IMAGE, "image_digest": digest})
    )
    for _ in range(120):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/v1/status", timeout=2) as response:
                if response.status == 200:
                    print(f"instance {name}: http://127.0.0.1:{port}  db={dbname}  bucket={env['S3_BUCKET']}  "
                          f"image={image.IMAGE}")
                    return
        except OSError:
            time.sleep(1)
    raise SystemExit(f"API did not come up; see 'docker logs {container}'")


def down(name: str, work_dir: Path, drop: bool) -> None:
    env = _db_env(name)
    state = work_dir / f"instance_{name}.json"
    container = container_name(name)
    logs = subprocess.run(["docker", "logs", container], capture_output=True, text=True)
    if logs.returncode == 0:
        work_dir.mkdir(parents=True, exist_ok=True)
        (work_dir / f"api_{name}.log").write_text(logs.stdout + logs.stderr)
    subprocess.run(["docker", "rm", "--force", container], capture_output=True, text=True)
    if state.is_file():
        state.unlink()
    if drop:
        dropped = image.run(["python", "-m", "snapshot.instance_admin", "drop"], env, check=False)
        if dropped.returncode != 0:
            raise SystemExit(f"could not drop the database and bucket:\n{dropped.stdout}\n{dropped.stderr}")


def restore(name: str, archive: Path) -> None:
    """Restore an archive into the empty instance ``name`` with ``tckdb_archive.py``."""
    archive = archive.resolve()
    done = image.run(
        ["python", "scripts/tckdb_archive.py", "restore", f"/restore/{archive.name}"],
        _db_env(name), mounts={archive.parent: "/restore"}, check=False,
    )
    if done.returncode != 0:
        raise SystemExit(f"restore failed:\n{done.stdout}\n{done.stderr}")
    print(done.stdout.strip())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("up", "down", "restore"):
        p = sub.add_parser(command)
        p.add_argument("--name", required=True, help="suffix: database tckdb_test_snapshot_<name>")
        p.add_argument("--work-dir", type=Path, default=REPO_ROOT / ".paper_snapshot_work")
        if command == "up":
            p.add_argument("--port", type=int, required=True)
        elif command == "restore":
            p.add_argument("--archive", type=Path, required=True)
        else:
            p.add_argument("--drop", action="store_true", help="also drop the database and empty the bucket")
    args = parser.parse_args(argv)
    if args.command == "up":
        up(args.name, args.port, args.work_dir)
    elif args.command == "restore":
        restore(args.name, args.archive)
    else:
        down(args.name, args.work_dir, args.drop)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

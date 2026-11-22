"""Run TCKDB from the container image ``pins.toml`` names, by digest.

The API, the migrations and every step that imports TCKDB code (the operator CLI, the custody check, the archive tool,
the expected-output generators, the PDep ingester, the CHEMKIN export check) run in that image, so the server and the
generators are the same build. The container shares the host's network (Postgres, the object store and the API port
are on ``127.0.0.1``) and runs as the invoking user, so the files it writes belong to them. This repository is mounted
read-only at ``/paper`` and the tckdb-adapters checkout at ``/adapters``; nothing of the ``tckdb/`` submodule is put
on the image's path.
"""

from __future__ import annotations

import json
import os
import subprocess
import tomllib
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
PINS = tomllib.loads((REPO_ROOT / "pins.toml").read_text())
#: The image, by the digest pins.toml records.
IMAGE = PINS["tckdb"]["image"].split(":")[0] + "@" + PINS["tckdb"]["image_digest"]
BACKEND = "/app/backend"
PAPER = "/paper"
ADAPTERS = "/adapters"
#: The database and object-store settings and the adapters checkout of the build in progress, set by ``build.py``
#: for the sources that build a payload in the image (``source_pdep``).
context: dict[str, Any] = {"env": {}, "adapters": None}
#: Variables passed into a container when they are set (``DB_*``, ``S3_*`` and the rest are given explicitly).
PASSED = ("RATE_LIMIT_ENABLED",)


def container_pythonpath(adapters: bool) -> str:
    """This repository, and the CHEMKIN and QCSchema adapters when a checkout is mounted."""
    paths = [PAPER]
    if adapters:
        paths += [f"{ADAPTERS}/adapters/tckdb_chemkin", f"{ADAPTERS}/adapters/tckdb_qcschema"]
    return os.pathsep.join(paths)


def docker_args(
    env: dict[str, str],
    *,
    mounts: dict[Path, str] | None = None,
    adapters: Path | None = None,
    writable: tuple[Path, ...] = (),
    name: str | None = None,
    detach: bool = False,
) -> list[str]:
    """``docker run`` options: host network, the invoking user, the paper repository read-only, ``env`` passed."""
    argv = ["docker", "run", "--network", "host", "--user", f"{os.getuid()}:{os.getgid()}", "--workdir", BACKEND]
    argv += ["--detach", "--name", name] if detach else ["--rm"]
    volumes = {REPO_ROOT: PAPER, **({adapters: ADAPTERS} if adapters else {}), **(mounts or {})}
    for host, inside in volumes.items():
        mode = "rw" if Path(host) in writable else "ro"
        argv += ["--volume", f"{Path(host).resolve()}:{inside}:{mode}"]
    variables = {"PYTHONPATH": container_pythonpath(adapters is not None), "HOME": "/tmp", **env}
    for key in PASSED:
        if key in os.environ and key not in variables:
            variables[key] = os.environ[key]
    for key, value in sorted(variables.items()):
        argv += ["--env", f"{key}={value}"]
    return [*argv, IMAGE]


def run(argv: list[str], env: dict[str, str], *, check: bool = True, **options: Any) -> subprocess.CompletedProcess:
    """Run ``argv`` in a throw-away container of the pinned image; raise with its output when it fails and ``check``."""
    done = subprocess.run([*docker_args(env, **options), *argv], capture_output=True, text=True)
    if check and done.returncode != 0:
        raise RuntimeError(f"{' '.join(argv)} failed in {IMAGE} ({done.returncode}):\n{done.stdout}\n{done.stderr}")
    return done


def start(argv: list[str], env: dict[str, str], name: str, **options: Any) -> str:
    """Start a named, detached container of the pinned image; return its id."""
    done = subprocess.run([*docker_args(env, name=name, detach=True, **options), *argv], capture_output=True, text=True)
    if done.returncode != 0:
        raise RuntimeError(f"could not start {name} from {IMAGE}:\n{done.stderr}")
    return done.stdout.strip()


def ensure_pulled() -> None:
    """Pull the pinned image when it is not present locally."""
    present = subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True, text=True)
    if present.returncode != 0:
        subprocess.run(["docker", "pull", IMAGE], check=True, capture_output=True, text=True)


def container_image_digest(name: str) -> str | None:
    """The digest of the image the named container runs, read with ``docker inspect``."""
    container = subprocess.run(["docker", "inspect", "--format", "{{.Image}}", name], capture_output=True, text=True)
    if container.returncode != 0:
        return None
    image_id = container.stdout.strip()
    image = subprocess.run(["docker", "image", "inspect", "--format", "{{json .}}", image_id], capture_output=True, text=True)
    if image.returncode != 0:
        return None
    document = json.loads(image.stdout)
    digests = [d.split("@", 1)[1] for d in document.get("RepoDigests") or [] if "@" in d]
    pinned = PINS["tckdb"]["image_digest"]
    if pinned in digests or image_id == pinned:
        return pinned
    return digests[0] if digests else image_id


def image_versions(env: dict[str, str]) -> dict[str, Any]:
    """Python and package versions inside the image, and where ``app`` is imported from."""
    code = (
        "import json, platform, importlib.metadata as m, app\n"
        "def v(n):\n"
        "    try:\n"
        "        return m.version(n)\n"
        "    except m.PackageNotFoundError:\n"
        "        return None\n"
        "print(json.dumps({'python': platform.python_version(), 'app_imported_from': app.__file__,"
        " 'packages': {n: v(n) for n in ('tckdb-backend', 'tckdb-schemas', 'cantera', 'rdkit', 'sqlalchemy')}}))"
    )
    return json.loads(run(["python", "-c", code], env).stdout)


def save(out: Path) -> dict[str, Any]:
    """``docker save`` the pinned image, gzipped, to ``out``; return its name, size and SHA-256."""
    import hashlib

    with out.open("wb") as fh:
        saver = subprocess.Popen(["docker", "save", IMAGE], stdout=subprocess.PIPE)
        gzip = subprocess.run(["gzip", "-n", "-6"], stdin=saver.stdout, stdout=fh)
        saver.stdout.close()
        if saver.wait() != 0 or gzip.returncode != 0:
            raise RuntimeError(f"docker save {IMAGE} failed")
    digest = hashlib.sha256()
    with out.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return {"file": out.name, "image": IMAGE, "bytes": out.stat().st_size, "sha256": digest.hexdigest()}

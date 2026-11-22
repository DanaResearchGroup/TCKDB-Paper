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
REPOSITORY = PINS["tckdb"]["image"].split(":")[0]
#: The image, by the digest of the multi-platform index pins.toml records.
IMAGE = REPOSITORY + "@" + PINS["tckdb"]["image_digest"]
#: The tag ``save`` writes into the saved file, and that ``docker load`` restores.
VERSION_TAG = PINS["tckdb"]["image_version_tag"]
#: Per platform (``linux/amd64``), the manifest and config digests of the image behind the index.
PLATFORMS: dict[str, dict[str, str]] = PINS["tckdb"].get("image_platforms") or {}
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
    return [*argv, reference()]


def run(argv: list[str], env: dict[str, str], *, check: bool = True, **options: Any) -> subprocess.CompletedProcess:
    """Run ``argv`` in a throw-away container of the pinned image; raise with its output when it fails and ``check``."""
    done = subprocess.run([*docker_args(env, **options), *argv], capture_output=True, text=True)
    if check and done.returncode != 0:
        raise RuntimeError(f"{' '.join(argv)} failed in {reference()} ({done.returncode}):\n{done.stdout}\n{done.stderr}")
    return done


def start(argv: list[str], env: dict[str, str], name: str, **options: Any) -> str:
    """Start a named, detached container of the pinned image; return its id."""
    done = subprocess.run([*docker_args(env, name=name, detach=True, **options), *argv], capture_output=True, text=True)
    if done.returncode != 0:
        raise RuntimeError(f"could not start {name} from {reference()}:\n{done.stderr}")
    return done.stdout.strip()


def pinned_as(image_id: str, repo_digests: list[str] | None, platform: str | None = None) -> str | None:
    """Which pinned identity an image is, from its ``docker image inspect`` ``Id`` and ``RepoDigests``, or ``None``.

    The pinned index digest (a pull by digest), or the manifest or config digest of one of the pinned platforms (a
    ``docker load`` of the saved file records the platform manifest; a classic image store reports the config); the
    platform's only when ``platform`` names it or is ``None``.
    """
    digests = {d.split("@", 1)[1] for d in repo_digests or [] if "@" in d}
    if PINS["tckdb"]["image_digest"] in digests | {image_id}:
        return "index " + PINS["tckdb"]["image_digest"]
    for name, ids in PLATFORMS.items():
        if platform not in (None, name):
            continue
        for kind in ("manifest", "config"):
            if ids.get(kind) and ids[kind] in digests | {image_id}:
                return f"{name} {kind} {ids[kind]}"
    return None


def _inspect_image(ref: str) -> dict[str, Any] | None:
    done = subprocess.run(["docker", "image", "inspect", "--format", "{{json .}}", ref], capture_output=True, text=True)
    if done.returncode != 0 or not done.stdout.strip():
        return None
    return json.loads(done.stdout)


def host_platform() -> str:
    done = subprocess.run(["docker", "version", "--format", "{{.Server.Os}}/{{.Server.Arch}}"], capture_output=True, text=True)
    return done.stdout.strip()


_resolved: list[str] = []


def local_reference() -> str | None:
    """A local reference to the pinned image without pulling: the index digest, else ``VERSION_TAG`` when it names a
    pinned identity for this host's platform (the image ``docker load`` restores from the saved file)."""
    if _inspect_image(IMAGE) is not None:
        return IMAGE
    loaded = _inspect_image(VERSION_TAG)
    if loaded is not None and pinned_as(loaded.get("Id", ""), loaded.get("RepoDigests"), host_platform()):
        return VERSION_TAG
    return None


def reference() -> str:
    """The reference containers are started from: a local copy of the pinned image when there is one, else ``IMAGE``,
    pulled by digest once. Never pulls when a pinned copy is present."""
    if not _resolved:
        local = local_reference()
        if local is None:
            subprocess.run(["docker", "pull", IMAGE], check=True, capture_output=True, text=True)
            local = IMAGE
        _resolved.append(local)
    return _resolved[0]


def ensure_pulled() -> str:
    """Resolve (and, only when no pinned copy is present, pull) the image; return the reference used."""
    return reference()


def container_image(name: str) -> dict[str, Any] | None:
    """The image the named container runs: its ``Id``, ``RepoDigests``, platform, and which pinned identity it is."""
    container = subprocess.run(["docker", "inspect", "--format", "{{.Image}}", name], capture_output=True, text=True)
    if container.returncode != 0 or not container.stdout.strip():
        return None
    image_id = container.stdout.strip()
    document = _inspect_image(image_id)
    if document is None:
        return {"id": image_id, "repo_digests": [], "platform": None, "pinned_as": None}
    platform = f"{document.get('Os')}/{document.get('Architecture')}" if document.get("Os") else None
    repo_digests = document.get("RepoDigests") or []
    return {
        "id": document.get("Id") or image_id,
        "repo_digests": repo_digests,
        "platform": platform,
        "pinned_as": pinned_as(document.get("Id") or image_id, repo_digests, platform),
    }


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


def saved_image(index: dict[str, Any], manifest: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The one image a ``docker save`` file holds, from its ``index.json`` and ``manifest.json``: tag, manifest and
    config digests. Attestation manifests are skipped; anything but exactly one tagged image gives ``None``."""
    images = [
        m for m in index.get("manifests") or []
        if not m.get("artifactType") and "io.containerd.manifest.subject" not in (m.get("annotations") or {})
    ]
    if len(images) != 1 or len(manifest) != 1 or len(manifest[0].get("RepoTags") or []) != 1:
        return None
    return {
        "tag": manifest[0]["RepoTags"][0],
        "manifest": images[0]["digest"],
        "config": "sha256:" + manifest[0]["Config"].rsplit("/", 1)[1],
    }


def save(out: Path) -> dict[str, Any]:
    """Save the pinned image for this host's platform, tagged ``VERSION_TAG``, gzipped, to ``out``.

    Returns the file's name, size and SHA-256 and the saved image's platform, manifest and config digests, read back
    from the file; raises unless the file holds exactly the pinned platform image under ``VERSION_TAG``.
    """
    import hashlib
    import tarfile

    platform = host_platform()
    pinned = PLATFORMS.get(platform)
    if not pinned:
        raise RuntimeError(f"pins.toml names no image for this host's platform {platform}")
    subprocess.run(["docker", "tag", reference(), VERSION_TAG], check=True, capture_output=True, text=True)
    with out.open("wb") as fh:
        saver = subprocess.Popen(["docker", "save", "--platform", platform, VERSION_TAG], stdout=subprocess.PIPE)
        gzip = subprocess.run(["gzip", "-n", "-6"], stdin=saver.stdout, stdout=fh)
        saver.stdout.close()
        if saver.wait() != 0 or gzip.returncode != 0:
            raise RuntimeError(f"docker save {VERSION_TAG} failed")
    with tarfile.open(out) as tar:
        manifest = json.load(tar.extractfile("manifest.json"))
        index = json.load(tar.extractfile("index.json"))
    found = saved_image(index, manifest)
    if found != {"tag": VERSION_TAG, "manifest": pinned["manifest"], "config": pinned["config"]}:
        raise RuntimeError(f"{out.name} does not hold the pinned {platform} image tagged {VERSION_TAG}: {found}")
    digest = hashlib.sha256()
    with out.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return {
        "file": out.name, "bytes": out.stat().st_size, "sha256": digest.hexdigest(), "tag": VERSION_TAG,
        "platform": platform, "manifest_digest": found["manifest"], "config_digest": found["config"],
        "index_digest": PINS["tckdb"]["image_digest"],
    }


if __name__ == "__main__":
    # Print the reference the snapshot scripts run (a local pinned copy, else the digest, pulled once).
    print(reference())

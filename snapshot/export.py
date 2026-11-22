"""Archive and expected-output export from the finished instance.

Runs ``backend/scripts/tckdb_archive.py`` and ``backend/scripts/ops/generate_expected_outputs.py`` in the pinned
TCKDB image (``image.py``) against the instance's database. The generators are this repository's
``tckdb_paper_generators``, mounted read-only; the output directory is the only writable mount.
"""

from __future__ import annotations

from pathlib import Path

import image


def create_archive(out: Path, env: dict[str, str]) -> str:
    out.parent.mkdir(parents=True, exist_ok=True)
    argv = ["python", "scripts/tckdb_archive.py", "create", f"/out/{out.name}", "--overwrite"]
    return image.run(argv, env, mounts={out.parent: "/out"}, writable=(out.parent,)).stdout


def verify_archive(path: Path, env: dict[str, str]) -> str:
    argv = ["python", "scripts/tckdb_archive.py", "verify", f"/out/{path.name}"]
    return image.run(argv, env, mounts={path.parent: "/out"}).stdout


def expected_outputs(out_dir: Path, env: dict[str, str], adapters: Path, only: list[str] | None = None) -> str:
    out_dir.mkdir(parents=True, exist_ok=True)
    argv = [
        "python",
        "scripts/ops/generate_expected_outputs.py",
        "--generators",
        "tckdb_paper_generators.registry:GENERATORS",
        "--output-dir",
        "/expected",
    ]
    for name in only or []:
        argv += ["--only", name]
    return image.run(argv, env, mounts={out_dir: "/expected"}, writable=(out_dir,), adapters=adapters).stdout

"""Compare the installed ``tckdb-backend``, ``tckdb-client`` and ``tckdb-schemas`` of this environment with the versions
the ``tckdb/`` submodule declares.

The versions are read in an isolated child of this interpreter (``-I``), so source directories on ``sys.path`` (and the
``*.egg-info`` an editable install leaves in them) do not stand in for the environment's own record.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

TCKDB_ROOT = Path(__file__).resolve().parents[1] / "tckdb"

#: Distribution name -> its pyproject file in the submodule.
DISTRIBUTIONS = {
    "tckdb-backend": TCKDB_ROOT / "backend" / "pyproject.toml",
    "tckdb-client": TCKDB_ROOT / "clients" / "python" / "pyproject.toml",
    "tckdb-schemas": TCKDB_ROOT / "schemas" / "python" / "tckdb-schemas" / "pyproject.toml",
}


def declared_version(pyproject: Path) -> str | None:
    match = re.search(r'^version\s*=\s*"([^"]+)"', pyproject.read_text(), flags=re.MULTILINE)
    return match.group(1) if match else None


_READ = (
    "import json, importlib.metadata as m\n"
    "def v(n):\n"
    "    try:\n"
    "        return m.version(n)\n"
    "    except m.PackageNotFoundError:\n"
    "        return None\n"
    "print(json.dumps({n: v(n) for n in %r}))"
)


def installed_versions() -> dict[str, str | None]:
    """The installed version of each TCKDB distribution in this environment."""
    done = subprocess.run(
        [sys.executable, "-I", "-c", _READ % sorted(DISTRIBUTIONS)], capture_output=True, text=True, check=True
    )
    return json.loads(done.stdout)


def installed_version_problems(names: tuple[str, ...] | None = None) -> list[str]:
    """One line per TCKDB distribution (of ``names``, default all) whose installed version is not the submodule's."""
    found = installed_versions()
    problems = []
    for name, pyproject in DISTRIBUTIONS.items():
        if names is not None and name not in names:
            continue
        declared, installed = declared_version(pyproject), found.get(name)
        if installed != declared:
            problems.append(f"{name}: installed {installed or 'nothing'}, the tckdb/ submodule declares {declared}")
    return problems

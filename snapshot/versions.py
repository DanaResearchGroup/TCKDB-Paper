"""Compare the installed ``tckdb-backend``, ``tckdb-client`` and ``tckdb-schemas`` with the versions the ``tckdb/``
submodule declares.

The versions are read in a child of this interpreter: isolated (``-I``), or with a given environment and working
directory.
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


def installed_versions(env: dict[str, str] | None = None, cwd: Path | None = None) -> dict[str, str | None]:
    """The installed version of each TCKDB distribution, as a child of this interpreter sees it.

    Without ``env`` the child runs isolated; with it, it runs with that environment and working directory.
    """
    code = _READ % sorted(DISTRIBUTIONS)
    argv = [sys.executable, "-c", code] if env is not None else [sys.executable, "-I", "-c", code]
    done = subprocess.run(argv, env=env, cwd=cwd, capture_output=True, text=True, check=True)
    return json.loads(done.stdout)


def installed_version_problems(env: dict[str, str] | None = None, cwd: Path | None = None) -> list[str]:
    """One line per TCKDB distribution whose installed version is not the one the submodule declares."""
    found = installed_versions(env, cwd)
    problems = []
    for name, pyproject in DISTRIBUTIONS.items():
        declared, installed = declared_version(pyproject), found.get(name)
        if installed != declared:
            problems.append(f"{name}: installed {installed or 'nothing'}, the tckdb/ submodule declares {declared}")
    return problems


def refuse_mismatched_install(what: str, env: dict[str, str] | None = None, cwd: Path | None = None) -> None:
    """Stop unless both the environment alone and, when given, a process started with ``env`` in ``cwd`` see the
    submodule's versions."""
    problems = installed_version_problems()
    if env is not None:
        problems += [f"{line} (as a process started like the API sees it)" for line in installed_version_problems(env, cwd)]
    if problems:
        raise SystemExit(
            f"{what} refused: the installed TCKDB packages are not the submodule's, so a release manifest would "
            "misstate its versions:\n  - " + "\n  - ".join(problems)
            + "\ninstall the submodule's packages into this environment (README.md, 'Set up')"
        )

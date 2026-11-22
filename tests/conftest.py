"""Test configuration: TCKDB's database fixtures and hooks, read from the pinned ``tckdb`` submodule.

The fixtures (``db_engine``, ``db_conn``, ``client``, ``db_session`` and the rest) and the harness hooks come from
``tckdb/backend/tests/conftest.py`` unchanged, so these tests run against the same scratch ``tckdb_test_*`` database
setup as TCKDB's own.

The CHEMKIN and QCSchema adapters come from the tckdb-adapters checkout named by ``TCKDB_ADAPTERS_ROOT`` (the commit in
``pins.toml``), put first on the path.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1] / "tckdb" / "backend"
_SOURCE = _BACKEND / "tests" / "conftest.py"

if not _SOURCE.is_file():
    raise RuntimeError(f"{_SOURCE} is missing; run 'git submodule update --init' to fetch the pinned TCKDB checkout")

ADAPTERS_ROOT = Path(os.environ.get("TCKDB_ADAPTERS_ROOT", "")).expanduser()
_ADAPTER_PATHS = [ADAPTERS_ROOT / "adapters" / name for name in ("tckdb_chemkin", "tckdb_qcschema")]
if not os.environ.get("TCKDB_ADAPTERS_ROOT") or not all((p / p.name).is_dir() for p in _ADAPTER_PATHS):
    raise RuntimeError(
        "set TCKDB_ADAPTERS_ROOT to a checkout of tckdb-adapters at the commit in pins.toml "
        "(it must hold adapters/tckdb_chemkin and adapters/tckdb_qcschema)"
    )
for _path in reversed(_ADAPTER_PATHS):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

_spec = importlib.util.spec_from_file_location("tckdb_backend_conftest", _SOURCE)
assert _spec is not None and _spec.loader is not None
_module = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _module
_spec.loader.exec_module(_module)

# The error-body floors are sized for TCKDB's own suite; this suite sends no error bodies.
_module.BODY_SWEEP_FLOORS.clear()

# Pytest finds fixtures and hooks by name in this module's namespace.
globals().update({name: value for name, value in vars(_module).items() if not name.startswith("__")})

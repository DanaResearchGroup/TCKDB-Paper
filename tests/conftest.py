"""Test configuration: TCKDB's database fixtures and hooks, read from the pinned ``tckdb`` submodule.

The fixtures (``db_engine``, ``db_conn``, ``client``, ``db_session`` and the rest) and the harness hooks come from
``tckdb/backend/tests/conftest.py`` unchanged, so these tests run against the same scratch ``tckdb_test_*`` database
setup as TCKDB's own.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1] / "tckdb" / "backend"
_SOURCE = _BACKEND / "tests" / "conftest.py"

if not _SOURCE.is_file():
    raise RuntimeError(f"{_SOURCE} is missing; run 'git submodule update --init' to fetch the pinned TCKDB checkout")

_spec = importlib.util.spec_from_file_location("tckdb_backend_conftest", _SOURCE)
assert _spec is not None and _spec.loader is not None
_module = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _module
_spec.loader.exec_module(_module)

# Pytest finds fixtures and hooks by name in this module's namespace.
globals().update({name: value for name, value in vars(_module).items() if not name.startswith("__")})

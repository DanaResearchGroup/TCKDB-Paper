"""``pins.toml`` agrees with the checked-out ``tckdb`` submodule and the tckdb-adapters checkout the tests use."""

from __future__ import annotations

import os
import re
import subprocess
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PINS = tomllib.loads((ROOT / "pins.toml").read_text())
ADAPTERS_ROOT = Path(os.environ["TCKDB_ADAPTERS_ROOT"]).expanduser()  # conftest refuses to run without it
ADAPTER_PACKAGE_FILES = {
    "tckdb-arc": "adapters/tckdb_arc/pyproject.toml",
    "tckdb-chemkin": "adapters/tckdb_chemkin/pyproject.toml",
    "tckdb-core": "tckdb_core/pyproject.toml",
    "tckdb-qcschema": "adapters/tckdb_qcschema/pyproject.toml",
}
PACKAGE_FILES = {
    "tckdb-client": "clients/python/pyproject.toml",
    "tckdb-schemas": "schemas/python/tckdb-schemas/pyproject.toml",
}


def test_the_submodule_is_at_the_pinned_commit():
    recorded = subprocess.run(
        ["git", "ls-tree", "HEAD", "tckdb"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.split()
    assert recorded[1] == "commit"
    assert recorded[2] == PINS["tckdb"]["commit"]
    head = subprocess.run(
        ["git", "-C", "tckdb", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()
    assert head == PINS["tckdb"]["commit"]


def test_the_image_tag_names_the_pinned_commit():
    assert PINS["tckdb"]["image"].endswith(f":sha-{PINS['tckdb']['commit']}")


def test_package_versions_match_the_pinned_checkout():
    for name, relative in PACKAGE_FILES.items():
        text = (ROOT / "tckdb" / relative).read_text()
        declared = re.search(r'^version\s*=\s*"([^"]+)"', text, flags=re.MULTILINE)
        assert declared and declared.group(1) == PINS["tckdb"]["packages"][name], name


def test_the_adapters_checkout_is_at_the_pinned_commit():
    head = subprocess.run(
        ["git", "-C", str(ADAPTERS_ROOT), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    assert head == PINS["tckdb_adapters"]["commit"]


def test_adapter_versions_match_the_pinned_adapters_checkout():
    for name, relative in ADAPTER_PACKAGE_FILES.items():
        text = (ADAPTERS_ROOT / relative).read_text()
        declared = re.search(r'^version\s*=\s*"([^"]+)"', text, flags=re.MULTILINE)
        assert declared and declared.group(1) == PINS["tckdb_adapters"][name], name


def test_the_postgres_image_is_pinned_by_digest_and_matches_tckdb_and_ci():
    image = PINS["environment"]["postgres_image"]
    assert "@sha256:" in image
    assert image in (ROOT / "tckdb" / "docker-compose.yml").read_text()
    assert image in (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    assert PINS["tckdb"]["image_digest"].startswith("sha256:")

"""``pins.toml`` agrees with the checked-out ``tckdb`` submodule."""

from __future__ import annotations

import re
import subprocess
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PINS = tomllib.loads((ROOT / "pins.toml").read_text())
PACKAGE_FILES = {
    "tckdb-client": "clients/python/pyproject.toml",
    "tckdb-chemkin": "clients/python/adapters/chemkin/pyproject.toml",
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

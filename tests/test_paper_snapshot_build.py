"""What the snapshot build writes to its public files, and what it refuses to record."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_DIR = ROOT / "snapshot"


@pytest.fixture(scope="module")
def build():
    sys.path.insert(0, str(SNAPSHOT_DIR))
    try:
        import build as module

        yield module
    finally:
        sys.path.remove(str(SNAPSHOT_DIR))


@pytest.fixture(scope="module")
def source_arc():
    sys.path.insert(0, str(SNAPSHOT_DIR))
    try:
        import source_arc as module

        yield module
    finally:
        sys.path.remove(str(SNAPSHOT_DIR))


CONFIG = {
    "sources": {
        "arc_runs": {
            "runs_root": "/data/arc_runs",
            "recorded_hosts": ["tckdb.example.org"],
            "timeout_seconds": 900,
            "callback": "https://tckdb.example.org/api/v1",
            "rights": {"license": "CC-BY-4.0"},
        }
    }
}


def test_the_record_carries_no_path_host_or_url(build):
    options = build.public_options(CONFIG["sources"]["arc_runs"])
    assert options == {"timeout_seconds": 900, "rights": {"license": "CC-BY-4.0"}}


def test_a_file_repeating_a_host_or_path_is_named(build):
    texts = {
        "clean.json": '{"timeout_seconds": 900}',
        "host.json": '{"host": "tckdb.example.org"}',
        "path.json": '{"root": "/data/arc_runs/run_1"}',
    }
    assert build.leaks(texts, CONFIG) == ["host.json", "path.json"]


def test_the_build_refuses_a_package_resolving_outside_the_submodule(build):
    assert build.outside_checkout() == {}


def test_a_source_archive_has_no_recordable_commit(source_arc, tmp_path):
    (tmp_path / "pkg").mkdir()
    assert source_arc.checkout_commit(tmp_path) is None
    assert source_arc.checkout_commit(tmp_path / "pkg") is None


def test_a_checkout_commit_is_its_head(source_arc):
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True)
    assert source_arc.checkout_commit(ROOT) == head.stdout.strip()
    assert source_arc.checkout_commit(ROOT / "snapshot") is None

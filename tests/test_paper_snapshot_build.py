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


def test_a_package_outside_the_submodule_is_reported(build, monkeypatch, tmp_path):
    import types

    outside = tmp_path / "elsewhere" / "app" / "__init__.py"
    outside.parent.mkdir(parents=True)
    outside.write_text("")
    fake = types.ModuleType("app")
    fake.__file__ = str(outside)
    monkeypatch.setitem(sys.modules, "app", fake)
    assert build.outside_checkout() == {"app": str(outside.resolve())}
    monkeypatch.undo()
    assert build.outside_checkout() == {}


def test_expanded_paths_and_the_home_directory_are_private(build, monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    config = {"sources": {"e2": {"root": "~/data/E2"}, "chemkin": {"fixture_dir": "tckdb/fixtures"}}}
    values = build.private_values(config)
    assert str(tmp_path / "data" / "E2") in values
    assert str(build.REPO_ROOT / "tckdb" / "fixtures") in values
    assert str(tmp_path) in values
    assert build.leaks({"a.json": f"see {tmp_path}/data/E2/job.log", "b.json": "clean"}, config) == ["a.json"]


def test_the_scan_covers_generated_directories_and_requires_the_report(build, tmp_path):
    with pytest.raises(SystemExit, match="build_report.json is missing"):
        build.output_texts(tmp_path, "{}")
    (tmp_path / "build_report.json").write_text("{}")
    (tmp_path / "expected_outputs").mkdir()
    (tmp_path / "expected_outputs" / "x.json").write_text('{"host": "tckdb.example.org"}')
    (tmp_path / "chemkin_export").mkdir()
    (tmp_path / "chemkin_export" / "chem.inp").write_text("ELEMENTS")
    (tmp_path / "tckdb.archive").write_text("tckdb.example.org")
    texts = build.output_texts(tmp_path, "{}")
    assert sorted(texts) == ["build_report.json", "chemkin_export/chem.inp", "expected_outputs/x.json", "snapshot_record.json"]
    assert build.leaks(texts, CONFIG) == ["expected_outputs/x.json"]


def test_a_leaking_file_is_renamed_so_it_cannot_pass_for_valid(build, tmp_path):
    (tmp_path / "build_report.json").write_text("leak")
    (tmp_path / "other.json").write_text("fine")
    assert build.withhold(tmp_path, ["build_report.json"]) == ["build_report.json.withheld"]
    assert not (tmp_path / "build_report.json").exists()
    assert (tmp_path / "build_report.json.withheld").read_text() == "leak"
    assert (tmp_path / "other.json").is_file()


def test_the_check_guard_needs_a_declared_checkout_that_app_came_from(tmp_path):
    from tckdb_paper_generators import chemkin_export

    app_file = tmp_path / "checkout" / "backend" / "app" / "__init__.py"
    app_file.parent.mkdir(parents=True)
    app_file.write_text("")
    assert chemkin_export.tckdb_root_problem(app_file, tmp_path / "checkout") is None
    assert "outside the declared" in chemkin_export.tckdb_root_problem(app_file, tmp_path / "other")
    assert "no TCKDB checkout is declared" in chemkin_export.tckdb_root_problem(app_file, None)

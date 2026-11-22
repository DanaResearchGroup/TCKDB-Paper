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


def _adapters_checkout(path: Path, *, git: bool = True) -> Path:
    for name in ("tckdb_chemkin", "tckdb_qcschema"):
        (path / "adapters" / name / name).mkdir(parents=True)
    if git:
        git_cmd = ["git", "-C", str(path), "-c", "user.name=test", "-c", "user.email=test@example.invalid"]
        subprocess.run([*git_cmd, "init", "-q"], check=True)
        subprocess.run([*git_cmd, "commit", "-q", "--allow-empty", "-m", "base"], check=True)
    return path


def test_the_adapters_checkout_is_required_and_must_be_recordable(build, tmp_path):
    assert "'adapter_path'" in build.adapter_problems({"sources": {}})[0]
    assert "tckdb_chemkin" in build.adapter_problems({"adapter_path": str(tmp_path / "empty")})[0]
    plain = _adapters_checkout(tmp_path / "plain", git=False)
    assert "git checkout" in build.adapter_problems({"adapter_path": str(plain)})[0]
    checkout = _adapters_checkout(tmp_path / "checkout")
    assert build.adapter_problems({"adapter_path": str(checkout)}) == []


def test_the_arc_source_must_use_the_same_adapters_checkout(build, tmp_path):
    checkout = _adapters_checkout(tmp_path / "checkout")
    other = _adapters_checkout(tmp_path / "other")
    same = {"adapter_path": str(checkout), "sources": {"arc_runs": {"adapter_path": str(checkout)}}}
    assert build.adapter_problems(same) == []
    differ = {"adapter_path": str(checkout), "sources": {"arc_runs": {"adapter_path": str(other)}}}
    assert "same tckdb-adapters checkout" in build.adapter_problems(differ)[0]


def test_the_arc_source_defaults_to_the_adapters_checkout(build, tmp_path):
    sources = tmp_path / "sources.yml"
    sources.write_text("adapter_path: /a/tckdb-adapters\nsources:\n  arc_runs: {enabled: true}\n")
    assert build.load_config(sources)["sources"]["arc_runs"]["adapter_path"] == "/a/tckdb-adapters"
    sources.write_text("adapter_path: /a\nsources:\n  arc_runs: {adapter_path: /b}\n")
    assert build.load_config(sources)["sources"]["arc_runs"]["adapter_path"] == "/b"


def test_the_adapters_are_imported_from_the_named_checkout(build, tmp_path):
    from conftest import ADAPTERS_ROOT

    assert build.outside_adapters(ADAPTERS_ROOT) == {}
    elsewhere = build.outside_adapters(tmp_path)
    assert sorted(elsewhere) == ["tckdb_chemkin", "tckdb_qcschema"]


def test_the_adapters_checkout_path_is_private(build, tmp_path):
    config = {"adapter_path": str(tmp_path / "tckdb-adapters"), "sources": {}}
    assert str(tmp_path / "tckdb-adapters") in build.private_values(config)
    assert build.leaks({"a.json": f"{tmp_path}/tckdb-adapters/adapters", "b.json": "clean"}, config) == ["a.json"]


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
    assert sorted(texts) == ["build_record.json", "build_report.json", "chemkin_export/chem.inp", "expected_outputs/x.json"]
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


@pytest.fixture(scope="module")
def versions():
    sys.path.insert(0, str(SNAPSHOT_DIR))
    try:
        import versions as module

        yield module
    finally:
        sys.path.remove(str(SNAPSHOT_DIR))


def test_the_installed_tckdb_packages_are_the_submodules(versions):
    assert versions.installed_version_problems() == []


def test_a_mismatched_install_is_refused(versions, monkeypatch):
    real = {name: versions.declared_version(path) for name, path in versions.DISTRIBUTIONS.items()}
    monkeypatch.setattr(versions, "installed_versions", lambda env=None, cwd=None: {**real, "tckdb-backend": "0.2.0"})
    problems = versions.installed_version_problems()
    assert len(problems) == 1 and problems[0].startswith("tckdb-backend: installed 0.2.0")
    with pytest.raises(SystemExit, match="the build refused"):
        versions.refuse_mismatched_install("the build")
    monkeypatch.setattr(versions, "installed_versions", lambda env=None, cwd=None: {})
    assert len(versions.installed_version_problems()) == 3


def _stale_egg_info(root: Path, version: str = "9.9.9") -> Path:
    info = root / "tckdb_schemas.egg-info"
    info.mkdir(parents=True)
    (info / "PKG-INFO").write_text(f"Metadata-Version: 2.1\nName: tckdb-schemas\nVersion: {version}\n")
    return root


def test_the_version_check_reads_what_a_process_on_the_source_path_sees(versions, tmp_path):
    import os

    declared = {name: versions.declared_version(path) for name, path in versions.DISTRIBUTIONS.items()}
    source_dirs = [str(p.parent) for p in versions.DISTRIBUTIONS.values()]
    backend = versions.TCKDB_ROOT / "backend"
    assert versions.installed_versions() == declared
    clean = {**os.environ, "PYTHONPATH": os.pathsep.join(source_dirs)}
    assert versions.installed_versions(clean, backend) == declared
    stale = _stale_egg_info(tmp_path / "stale")
    shadowed = {**os.environ, "PYTHONPATH": os.pathsep.join([str(stale), *source_dirs])}
    assert versions.installed_versions(shadowed, backend)["tckdb-schemas"] == "9.9.9"
    assert versions.installed_version_problems(shadowed, backend) == [
        f"tckdb-schemas: installed 9.9.9, the tckdb/ submodule declares {declared['tckdb-schemas']}"
    ]
    assert versions.installed_version_problems() == []


def test_the_build_checks_the_view_of_the_processes_it_starts(build, tmp_path):
    from conftest import ADAPTERS_ROOT

    paths = [*build.PACKAGE_PATHS, *build.adapter_package_paths(ADAPTERS_ROOT)]
    assert build.install_problems(paths) == []
    stale = _stale_egg_info(tmp_path / "stale")
    problems = build.install_problems([stale, *paths])
    assert len(problems) == 1 and problems[0].startswith("tckdb-schemas: installed 9.9.9")


def _pins(**commits):
    import tomllib

    pins = tomllib.loads((ROOT / "pins.toml").read_text())
    for section, commit in commits.items():
        pins[section]["commit"] = commit
    return pins


def test_the_submodule_and_adapters_commits_must_be_the_pinned_ones(build, tmp_path):
    from conftest import ADAPTERS_ROOT

    config = {"adapter_path": str(ADAPTERS_ROOT)}
    assert build.pin_problems(config, _pins()) == []
    assert build.pin_problems(config, _pins(tckdb="0" * 40)) == [
        f"the tckdb/ submodule is at {build.submodule_commit()}, pins.toml names {'0' * 40}"
    ]
    other = _adapters_checkout(tmp_path / "other")
    (problem,) = build.pin_problems({"adapter_path": str(other)}, _pins())
    assert problem.startswith("the tckdb-adapters checkout is at ") and problem.endswith(_pins()["tckdb_adapters"]["commit"])
    assert build.pin_problems({"adapter_path": str(other)}, _pins(tckdb_adapters=build.source_arc.checkout_commit(other))) == []


def _edits_document(sqlstate: str = "55000", control_restored: bool = True) -> dict:
    refused = {"refused": True, "sqlstate": sqlstate, "message": "accepted kinetics record k is immutable"}
    return {
        "approved_records": [
            {
                "kinetics_ref": "kin_a",
                "a_after_rollback_equals_a_before": True,
                "attempts": [{"attempt": "change A", **refused}, {"attempt": "delete", **refused}],
            }
        ],
        "control_rejected_records": [
            {
                "kinetics_ref": "kin_b",
                "a_after_rollback_equals_a_before": control_restored,
                "attempts": [{"attempt": "change A", "refused": False, "rows_affected": 1}],
            }
        ],
        "expected_sqlstate_of_a_refusal": sqlstate,
    }


def test_the_refusal_sqlstate_is_the_builds_not_the_documents(build):
    assert build.edit_refusal_problems(_edits_document()) == []
    problems = build.edit_refusal_problems(_edits_document(sqlstate="XX000"))
    assert len(problems) == 2 and all("was not refused as immutable" in p for p in problems)


def test_the_control_must_be_restored_after_its_rollback(build):
    assert build.edit_refusal_problems(_edits_document(control_restored=False)) == ["control kin_b: A changed"]

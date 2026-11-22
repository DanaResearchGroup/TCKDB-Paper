"""Build the demonstration snapshot on an empty local TCKDB instance.

    python snapshot/build.py --sources snapshot/sources.example.yml

Steps:

1. validate the sources config, then check the instance is reachable and empty;
2. register a depositor and mint its API key;
3. deposit each configured source through its public route;
4. create a curator and curate: approval, the caught error, the release (a demonstration, recorded as such);
5. export the use case as a CHEMKIN mechanism as the curator (``chemkin_export`` in the sources file);
6. export the archive and the expected outputs; the CHEMKIN output must show the files loaded in Cantera;
7. write ``build_report.json`` (warnings and refusals by code) and ``build_record.json``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
TCKDB_ROOT = REPO_ROOT / "tckdb"
PACKAGE_PATHS = [
    TCKDB_ROOT / "schemas" / "python" / "tckdb-schemas",
    TCKDB_ROOT / "clients" / "python" / "src",
    TCKDB_ROOT / "backend",
    REPO_ROOT,
]
# This checkout's packages come first on the path. The adapters' are added from ``adapter_path`` once the sources file
# is read.
for _path in reversed([HERE, *PACKAGE_PATHS]):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import yaml  # noqa: E402

import curation  # noqa: E402
import export  # noqa: E402
import source_arc  # noqa: E402
import source_chemkin  # noqa: E402
import source_e2  # noqa: E402
import source_pdep  # noqa: E402
import use_case_export  # noqa: E402
from common import ADAPTER_PACKAGES, Report, Session, adapter_package_paths  # noqa: E402
from versions import installed_version_problems, refuse_mismatched_install  # noqa: E402

#: Generators run for the snapshot.
EXPECTED_OUTPUTS = (
    "corpus_counts",
    "conformer_basins",
    "calculation_evidence",
    "deposit_warnings",
    "hessian_reanalysis",
    "thermo_selection_outcomes",
    "structure_selection_outcomes",
    "mechanism_roundtrip_counts",
    "mechanism_fixture_provenance",
    "selected_thermo_by_species",
    "candidate_lineage",
    "transition_state_evidence",
    "use_case_ch4_oh",
    "approved_record_edits",
    "use_case_chemkin_export",
    "ch3_enthalpy_of_formation",
    "network_n2h3",
    "chemkin_reconciliation",
    "species_thermo_sources",
    "caught_error",
    "dataset_release",
)

#: Config keys holding local paths or host names; omitted from ``build_record.json``.
PATH_KEYS = frozenset({"root", "fixture_dir", "adapter_path", "arc_path", "runs_root", "arkane_dir", "recorded_hosts"})
TOP_LEVEL_KEYS = frozenset(
    {"instance", "adapter_path", "sources", "accounts", "expected_outputs", "curation", "chemkin_export"}
)

#: Deposit order.
SOURCES = (
    ("e2_conformers", source_e2),
    ("chemkin_formic_acid", source_chemkin),
    ("arc_runs", source_arc),
    ("pdep_network", source_pdep),
)


def load_config(path: Path) -> dict[str, Any]:
    config = yaml.safe_load(path.read_text()) or {}
    config.setdefault("instance", {})
    config.setdefault("sources", {})
    arc = (config["sources"] or {}).get("arc_runs")
    if isinstance(arc, dict) and config.get("adapter_path") and not arc.get("adapter_path"):
        arc["adapter_path"] = config["adapter_path"]  # the ARC adapter comes from the same checkout
    return config


def registered_generators() -> set[str]:
    """Generator names in the registry, read as text."""
    text = (REPO_ROOT / "tckdb_paper_generators" / "registry.py").read_text()
    return set(re.findall(r'^\s+"([a-z0-9_]+)":\s', text, flags=re.MULTILINE))


def adapters_checkout(config: dict[str, Any]) -> Path:
    return Path(str(config.get("adapter_path") or "")).expanduser()


def adapter_problems(config: dict[str, Any]) -> list[str]:
    """``adapter_path`` names a git checkout of tckdb-adapters, and the ARC source names the same one."""
    if not config.get("adapter_path"):
        return ["'adapter_path' (a git checkout of tckdb-adapters, for the CHEMKIN and QCSchema adapters) is required"]
    root = adapters_checkout(config)
    missing = [p for p in adapter_package_paths(root) if not (p / p.name).is_dir()]
    if missing:
        names = ", ".join(p.relative_to(root).as_posix() + "/" + p.name for p in missing)
        return [f"'adapter_path' must be a tckdb-adapters checkout ({names} not found)"]
    if source_arc.checkout_commit(root) is None:
        return ["'adapter_path' must be a git checkout of tckdb-adapters, so its commit can be recorded"]
    arc = (config.get("sources") or {}).get("arc_runs") or {}
    if arc.get("enabled", True) and arc.get("adapter_path"):
        if Path(str(arc["adapter_path"])).expanduser().resolve() != root.resolve():
            return ["sources.arc_runs.adapter_path must name the same tckdb-adapters checkout as 'adapter_path'"]
    return []


def curation_problems(config: dict[str, Any]) -> list[str]:
    """The curation plan names only deposited ARC runs and states every text it writes."""
    plan = config.get("curation") or {}
    arc = (config.get("sources") or {}).get("arc_runs") or {}
    runs = set(arc.get("runs") or []) if arc.get("enabled", True) else set()
    problems = [f"curation: unknown key {k!r}" for k in sorted(set(plan) - {"caught_error", "release", "use_case"})]
    use_case = plan.get("use_case")
    if use_case is not None and (use_case or {}).get("run") not in runs:
        problems.append(f"curation.use_case: run {(use_case or {}).get('run')!r} is not in sources.arc_runs.runs")
    caught = plan.get("caught_error")
    if caught:
        if caught.get("run") not in runs:
            problems.append(f"curation.caught_error: run {caught.get('run')!r} is not in sources.arc_runs.runs")
        finding = caught.get("finding") or {}
        problems += [f"curation.caught_error.finding: {k!r} is required" for k in ("kind", "verdict", "rationale") if not finding.get(k)]
        problems += [f"curation.caught_error: {k!r} is required" for k in ("reject_note", "approve_note") if not caught.get(k)]
    release = plan.get("release")
    if release:
        needed = ("tag", "title", "citation_text", "contact", "policy", "selections")
        problems += [f"curation.release: {k!r} is required" for k in needed if not release.get(k)]
        for item in release.get("selections") or []:
            if item.get("run") not in runs:
                problems.append(f"curation.release: selection run {item.get('run')!r} is not in sources.arc_runs.runs")
            if item.get("record") not in ("kinetics", "transition_state_entry", "thermo") or not item.get("rationale"):
                problems.append(f"curation.release: selection {item} needs a record kind and a rationale")
            if item.get("record") == "thermo" and not item.get("smiles"):
                problems.append(f"curation.release: thermo selection {item} names no smiles")
    return problems


EDITS_OUTPUT = "approved_record_edits"


def edit_refusal_problems(document: dict[str, Any]) -> list[str]:
    """What the edits output fails to show: every attempt on an approved record refused by the database's trigger, the
    value unchanged, and the same change accepted on at least one never-approved record (so the refusal is the
    approval's doing, not a read-only session's)."""
    out: list[str] = []
    approved = document.get("approved_records") or []
    controls = document.get("control_rejected_records") or []
    if not approved:
        out.append("no approved computed rate record of the use case was tried")
    if not controls:
        out.append("no rejected rate record was tried as the control")
    sqlstate = document.get("expected_sqlstate_of_a_refusal")
    for row in approved:
        for attempt in row["attempts"]:
            if not attempt.get("refused") or attempt.get("sqlstate") != sqlstate or "is immutable" not in (attempt.get("message") or ""):
                out.append(f"{row['kinetics_ref']}: {attempt['attempt']} was not refused as immutable: {attempt}")
        if not row.get("a_after_rollback_equals_a_before"):
            out.append(f"{row['kinetics_ref']}: A changed")
    for row in controls:
        for attempt in row["attempts"]:
            if attempt.get("refused") or attempt.get("rows_affected") != 1:
                out.append(f"control {row['kinetics_ref']}: {attempt['attempt']} was not accepted: {attempt}")
    return out


def validate_config(config: dict[str, Any]) -> list[str]:
    """Return the problems in the whole config, enabled stub sources included."""
    problems = [f"unknown top-level key {k!r}" for k in sorted(set(config) - TOP_LEVEL_KEYS)]
    problems += adapter_problems(config)
    known = {name for name, _ in SOURCES}
    sources = config.get("sources") or {}
    problems += [f"unknown source {k!r}; known: {sorted(known)}" for k in sorted(set(sources) - known)]
    for name, module in SOURCES:
        entry = sources.get(name)
        if entry and entry.get("enabled", True):
            problems += module.validate(entry)
    if not any(e and e.get("enabled", True) for e in sources.values()):
        problems.append("no source is enabled; there is nothing to build")
    problems += curation_problems(config)
    problems += use_case_export.problems(config)
    if config.get("chemkin_export") and not config.get("curation"):
        problems.append("chemkin_export needs the curation block: the export is requested as the curator")
    wanted = config.get("expected_outputs")
    if wanted:
        problems += [f"unknown generator {n!r}" for n in wanted if n not in registered_generators()]
    return problems


def database_env(instance: dict[str, Any]) -> dict[str, str]:
    db = instance.get("database") or {}
    s3 = instance.get("s3") or {}
    env = {
        "DB_USER": str(db.get("user", os.environ.get("DB_USER", "tckdb"))),
        "DB_PASSWORD": str(db.get("password", os.environ.get("DB_PASSWORD", "tckdb"))),
        "DB_HOST": str(db.get("host", os.environ.get("DB_HOST", "127.0.0.1"))),
        "DB_PORT": str(db.get("port", os.environ.get("DB_PORT", "5432"))),
        "DB_NAME": str(db.get("name", os.environ.get("DB_NAME", "tckdb_dev"))),
    }
    for key, default in (
        ("endpoint_url", "http://localhost:9000"),
        ("access_key", "tckdb"),
        ("secret_key", "tckdb_secret"),
        ("bucket", "tckdb-artifacts"),
    ):
        env["S3_" + key.upper()] = str(s3.get(key, os.environ.get("S3_" + key.upper(), default)))
    return env


def assert_empty(env: dict[str, str]) -> None:
    import psycopg

    with psycopg.connect(
        host=env["DB_HOST"], port=env["DB_PORT"], user=env["DB_USER"], password=env["DB_PASSWORD"], dbname=env["DB_NAME"]
    ) as conn:
        counts = {t: conn.execute(f"select count(*) from {t}").fetchone()[0] for t in ("submission", "species", "app_user")}
    if counts["submission"] or counts["species"]:
        raise SystemExit(f"instance {env['DB_NAME']} is not empty ({counts}); the snapshot is built from an empty instance")
    if counts["app_user"]:
        print(f"note: {counts['app_user']} account(s) already exist; they will be reused by name or the build will stop", file=sys.stderr)


def git_commit(adapters: Path) -> dict[str, Any]:
    def run(*argv: str) -> str:
        return subprocess.run(["git", *argv], cwd=REPO_ROOT, capture_output=True, text=True).stdout.strip()

    return {
        "commit": run("rev-parse", "HEAD"),
        "dirty_tracked_files": len(run("status", "--porcelain", "--untracked-files=no").splitlines()),
        "tckdb_commit": run("-C", "tckdb", "rev-parse", "HEAD"),
        "tckdb_adapters_commit": source_arc.checkout_commit(adapters),
    }


def _declared_version(path: Path) -> str:
    match = re.search(r'^version\s*=\s*"([^"]+)"', path.read_text(), flags=re.MULTILINE)
    return match.group(1) if match else "unknown"


def package_versions(adapters: Path) -> dict[str, Any]:
    """Versions declared by the pyproject files of the submodule and the adapters checkout, and whether the build
    imported the packages from there.

    Installed-distribution metadata can describe another checkout (an editable install made elsewhere), so the
    declared version comes from the files and the import location is checked separately.
    """
    declared = {
        "tckdb-client": _declared_version(TCKDB_ROOT / "clients" / "python" / "pyproject.toml"),
        "tckdb-schemas": _declared_version(TCKDB_ROOT / "schemas" / "python" / "tckdb-schemas" / "pyproject.toml"),
    }
    adapter_declared = {
        path.name.replace("_", "-"): _declared_version(path / "pyproject.toml")
        for path in adapter_package_paths(adapters)
    }
    return {
        "declared_by_this_checkout": declared,
        "installed_matches_this_checkout": not installed_version_problems(),
        "imported_from_this_checkout": not outside_checkout(),
        "declared_by_the_adapters_checkout": adapter_declared,
        "imported_from_the_adapters_checkout": not outside_adapters(adapters),
    }


def outside_checkout() -> dict[str, str]:
    """The TCKDB packages this process imported from outside the ``tckdb/`` submodule, by name."""
    import app
    import tckdb_client
    import tckdb_schemas

    root = TCKDB_ROOT.resolve()
    modules = {"app": app, "tckdb_client": tckdb_client, "tckdb_schemas": tckdb_schemas}
    return {
        name: str(Path(module.__file__).resolve())
        for name, module in modules.items()
        if root not in Path(module.__file__).resolve().parents
    }


def outside_adapters(adapters: Path) -> dict[str, str]:
    """The adapter packages this process imports from outside the tckdb-adapters checkout, by name."""
    import importlib

    root = adapters.resolve()
    found = {}
    for name in ADAPTER_PACKAGES:
        origin = Path(importlib.import_module(name).__file__).resolve()
        if root not in origin.parents:
            found[name] = str(origin)
    return found


def public_options(entry: dict[str, Any]) -> dict[str, Any]:
    """A source's options without local paths, host names or any URL."""
    return {k: v for k, v in entry.items() if k not in PATH_KEYS and not _has_url(v)}


def _has_url(value: Any) -> bool:
    if isinstance(value, str):
        return "://" in value
    if isinstance(value, dict):
        return any(_has_url(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return any(_has_url(v) for v in value)
    return False


def private_values(config: dict[str, Any]) -> list[str]:
    """The local paths and host names the sources file holds, which no output file may repeat.

    Each path is also taken in its expanded absolute form (``~`` and relative paths resolved), and the home directory
    is always included.
    """
    found: set[str] = {str(Path.home())}
    for entry in [{"adapter_path": config.get("adapter_path")}, *(config.get("sources") or {}).values()]:
        for key in PATH_KEYS:
            value = (entry or {}).get(key)
            for item in value if isinstance(value, list) else [value]:
                if not item:
                    continue
                found.add(str(item))
                if key != "recorded_hosts":
                    path = Path(str(item)).expanduser()
                    found.add(str(path))
                    found.add(str((path if path.is_absolute() else REPO_ROOT / path).resolve()))
                    found.add(str(path.resolve()))
    return sorted(found)


def leaks(texts: dict[str, str], config: dict[str, Any]) -> list[str]:
    """Names of the output files that repeat a path or host name of the sources file."""
    private = private_values(config)
    return sorted(name for name, text in texts.items() if any(value in text for value in private))


def output_texts(out_dir: Path, record_text: str) -> dict[str, str]:
    """The publishable outputs by name: the report (required), the record, ``expected_outputs/``, ``chemkin_export/``.

    The archive and its job files are deposited verbatim and are not read here.
    """
    report = out_dir / "build_report.json"
    if not report.is_file():
        raise SystemExit(f"{report} is missing; the build cannot show its outputs are free of local paths and hosts")
    texts = {"build_record.json": record_text}
    for path in [report, *sorted(p for d in ("expected_outputs", "chemkin_export") for p in (out_dir / d).rglob("*") if p.is_file())]:
        texts[path.relative_to(out_dir).as_posix()] = path.read_text(encoding="utf-8", errors="replace")
    return texts


def withhold(out_dir: Path, names: list[str]) -> list[str]:
    """Rename each leaking file to ``<name>.withheld`` so it cannot pass for a valid output; return the new names."""
    renamed = []
    for name in names:
        source = out_dir / name
        if source.is_file():
            source.rename(source.with_name(source.name + ".withheld"))
            renamed.append(name + ".withheld")
    return renamed


def source_records(config: dict[str, Any], report: Report) -> dict[str, Any]:
    """Per source: its options without any path on this machine, and a digest of the files it read."""
    records: dict[str, Any] = {}
    for name, module in SOURCES:
        entry = (config["sources"] or {}).get(name)
        if not entry:
            records[name] = {"status": report.source(name)["status"]}
            continue
        records[name] = {
            "status": report.source(name)["status"],
            "options": public_options(entry),
            "input_files": module.describe_inputs(entry) if entry.get("enabled", True) else {},
        }
        if "literature" in report.source(name):
            records[name]["literature"] = report.source(name)["literature"]
    return records


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sources", type=Path, required=True, help="sources config (see sources.example.yml)")
    parser.add_argument("--out-dir", type=Path, default=None, help="where the snapshot is written (default: <work-dir>/snapshot)")
    parser.add_argument("--work-dir", type=Path, default=REPO_ROOT / ".paper_snapshot_work")
    parser.add_argument("--skip-approval", action="store_true")
    parser.add_argument("--skip-export", action="store_true")
    parser.add_argument("--allow-nonempty", action="store_true", help="skip the empty-instance check (reruns only)")
    args = parser.parse_args(argv)

    refuse_mismatched_install("the build")
    stray = outside_checkout()
    if stray:
        raise SystemExit(
            "these packages resolve outside the tckdb/ submodule: "
            + ", ".join(f"{name} ({path})" for name, path in sorted(stray.items()))
            + "; install the submodule's packages (see README.md) or put them first on PYTHONPATH"
        )
    config = load_config(args.sources)
    problems = validate_config(config)
    if problems:
        print("The sources config is not valid; nothing was deposited:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 2
    adapters = adapters_checkout(config)
    package_paths = [*PACKAGE_PATHS, *adapter_package_paths(adapters)]
    for _path in reversed(adapter_package_paths(adapters)):
        sys.path.insert(0, str(_path))
    stray = outside_adapters(adapters)
    if stray:
        raise SystemExit(
            "these packages resolve outside the tckdb-adapters checkout named by 'adapter_path': "
            + ", ".join(f"{name} ({path})" for name, path in sorted(stray.items()))
        )
    instance = config["instance"]
    base_url = instance.get("api_url", "http://127.0.0.1:8010")
    out_dir = (args.out_dir or args.work_dir / "snapshot").resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    db_env = database_env(instance)
    accounts = config.get("accounts") or {}
    depositor = {"username": "snapshot_depositor", "password": "snapshot-depositor-pass", "email": "depositor@snapshot.invalid",
                 "full_name": "Snapshot build depositor", **(accounts.get("depositor") or {})}
    curator = {"username": "snapshot_curator", "password": "snapshot-curator-pass", "email": "curator@snapshot.invalid",
               "full_name": "Snapshot build curator (script)", **(accounts.get("curator") or {})}

    session = Session(base_url)
    status = session.health()
    print(f"instance {session.base}: status={status.get('status')} revision={status['components']['database']['alembic_revision']}")
    if not args.allow_nonempty:
        assert_empty(db_env)

    report = Report()
    started = time.time()
    session.register_depositor(**depositor)

    approval: dict[str, Any] = {"performed": False}
    exports: dict[str, Any] = {}
    try:
        for name, module in SOURCES:
            entry = (config["sources"] or {}).get(name)
            if not entry:
                report.source(name)["status"] = "skipped: no entry in the sources config"
                print(f"[{name}] skipped (no config entry)")
                continue
            if not entry.get("enabled", True):
                report.source(name)["status"] = "skipped: enabled is false"
                print(f"[{name}] skipped (enabled: false)")
                continue
            print(f"[{name}] depositing ...")
            module.deposit(session, entry, report, args.work_dir)
            print(f"[{name}] {report.source(name)['status']}: {report.source(name)['counts']}")

        if not args.skip_approval:
            print("[curation] creating curator and approving submissions ...")
            created = curation.create_curator(db_env, curator["username"], curator["password"], curator["email"], curator["full_name"])
            plan = config.get("curation") or {}
            caught = plan.get("caught_error")
            hold = frozenset({curation.arc_response(report, caught["run"])["submission_ref"]}) if caught else frozenset()
            reviewer = curation.Curator(session, curator["username"], curator["password"])
            try:
                outcome = curation.approve_all(reviewer, report, hold=hold)
                approval = {"performed": True, "curator_account": created, **outcome,
                            "statement": "approval was done by the build script for a demonstration; it is not an independent review"}
                print(f"[curation] approved {outcome['approved_submissions']} submissions; held {len(hold)} for record review")
                if caught:
                    approval["caught_error"] = curation.review_caught_error(reviewer, report, caught)
                    print(f"[curation] {caught['run']}: {len(approval['caught_error']['rejected'])} records rejected, "
                          f"{len(approval['caught_error']['approved'])} approved")
                if plan.get("release"):
                    approval["release"] = curation.cut_release(
                        reviewer, report, plan["release"], export.subprocess_env(db_env, package_paths)
                    )
                    print(f"[curation] release {plan['release']['tag']} published")
                if config.get("chemkin_export"):
                    approval["chemkin_export"] = use_case_export.export_use_case(
                        reviewer, report, config["chemkin_export"], out_dir, approval.get("release")
                    )
                    print(f"[chemkin_export] {sorted(approval['chemkin_export']['files'])} written")
                if plan.get("use_case"):
                    run = plan["use_case"]["run"]
                    approval["use_case_grades"] = curation.grade_use_case(reviewer, report, run)
                    approval["approved_calculation_file_refused"] = curation.add_file_to_approved_calculation(
                        session, reviewer, report, run
                    )
                    print(f"[curation] {run}: {len(approval['use_case_grades']['graded'])} records graded; "
                          f"adding a file to an approved calculation answered "
                          f"{approval['approved_calculation_file_refused']['status_code']}")
            finally:
                reviewer.close()

        if not args.skip_export:
            env = export.subprocess_env(db_env, package_paths)
            archive = out_dir / "tckdb.archive"
            print("[export] archive ...")
            written = export.create_archive(archive, env).strip().splitlines()
            exports["archive_summary"] = written[-1] if written else ""
            verified = export.verify_archive(archive, env).strip().splitlines()
            exports["archive_verify"] = [ln for ln in verified if not ln.startswith("Checked ")]
            print("[export] expected outputs ...")
            wanted = list(config.get("expected_outputs") or EXPECTED_OUTPUTS)
            printed = export.expected_outputs(out_dir / "expected_outputs", env, only=wanted).splitlines()
            if config.get("chemkin_export"):
                if use_case_export.OUTPUT_NAME not in wanted:
                    raise SystemExit(f"chemkin_export is configured but expected_outputs does not list {use_case_export.OUTPUT_NAME}")
                document = json.loads((out_dir / "expected_outputs" / f"{use_case_export.OUTPUT_NAME}.json").read_text())
                refused = use_case_export.verify_output(document)
                if refused:
                    raise SystemExit("the CHEMKIN export is not shown loaded and checked:\n  - " + "\n  - ".join(refused))
                exports["chemkin_export_saved_files_vs_in_process_export"] = use_case_export.check_saved(
                    out_dir / use_case_export.DIRECTORY, env
                )
            if EDITS_OUTPUT in wanted:
                refused = edit_refusal_problems(json.loads((out_dir / "expected_outputs" / f"{EDITS_OUTPUT}.json").read_text()))
                if refused:
                    raise SystemExit("the refusal of edits to approved records is not shown:\n  - " + "\n  - ".join(refused))
            exports["expected_outputs"] = [ln for ln in printed if re.match(r"^[0-9a-f]{64}  ", ln)]
            exports["archive_sha256"] = hashlib.sha256(archive.read_bytes()).hexdigest()

    finally:
        report.write(out_dir / "build_report.json")
    record = {
        "snapshot": "TCKDB paper demonstration snapshot",
        "source_commit": git_commit(adapters),
        "packages": package_versions(adapters),
        "sources": source_records(config, report),
        "approval": approval,
        "exports": exports,
        "built_at_unix": int(started),
        "wall_seconds": round(time.time() - started, 1),
    }
    record_text = json.dumps(record, indent=2, sort_keys=True, default=str) + "\n"
    (out_dir / "build_record.json").write_text(record_text)
    leaked = leaks(output_texts(out_dir, record_text), config)
    if leaked:
        withheld = withhold(out_dir, leaked)
        raise SystemExit(
            f"{', '.join(leaked)} repeat a local path or host name from the sources file; renamed to "
            f"{', '.join(withheld)}, which are not publishable"
        )
    print(f"done in {record['wall_seconds']} s; wrote {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

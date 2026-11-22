"""Source 3: the N2H3 pressure-dependent network (Keslin, Kaplan and Grinberg Dana, PCCP 2025, 27, 2680).

The Arkane run directory is turned into one ``NetworkPDepUploadRequest`` by the PDep ingester
(``backend/scripts/pdep_ingestion``, which reads ``input.py``, ``output.py`` and ``supporting_information.csv``), run in
the pinned TCKDB image by ``pdep_payload.py``, and posted to ``/uploads/networks/pdep`` from the host. The deposit cites the paper by DOI (``literature``). What the ingester could not
carry over is recorded under ``ingestion`` in the build report, and the rate of one channel at a reference point, from
the fit Arkane wrote to ``chem.inp``, under ``arkane_reference_rate``.

Entry::

    pdep_network:
      enabled: true
      arkane_dir: /path/to/Final_Final_CCSDT_F12_Aug_F12
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import image
from common import Report, Session, TCKDBError, collect_response_warnings, digest_files

SOURCE = "pdep_network"
READ_FILES = ("input.py", "output.py", "supporting_information.csv", "chem.inp")

#: The cited publication. The literature payload has no author field.
DEFAULT_LITERATURE = {
    "kind": "article",
    "title": "Pressure-dependent kinetic analysis of the N2H3 potential energy surface",
    "journal": "Physical Chemistry Chemical Physics",
    "year": 2025,
    "volume": "27",
    "pages": "2680-2691",
    "doi": "10.1039/d4cp03837a",
}


def validate(cfg: dict[str, Any]) -> list[str]:
    """Return the problems with this source's config."""
    if not cfg.get("arkane_dir"):
        return [f"{SOURCE}: 'arkane_dir' (the Arkane run directory) is required"]
    root = Path(str(cfg["arkane_dir"])).expanduser()
    return [f"{SOURCE}: {name} not found under arkane_dir" for name in READ_FILES[:2] if not (root / name).is_file()]


def describe_inputs(cfg: dict[str, Any]) -> dict[str, Any]:
    """Return the count and digest of the files the ingester reads."""
    root = Path(cfg["arkane_dir"]).expanduser()
    return digest_files(root, [root / name for name in READ_FILES if (root / name).is_file()])


def deposit(session: Session, cfg: dict[str, Any], report: Report, work_dir: Path) -> None:
    root = Path(cfg["arkane_dir"]).expanduser().resolve()
    src = report.source(SOURCE)
    built = json.loads(
        image.run(
            ["python", "-m", "snapshot.pdep_payload", "/arkane"], image.context["env"],
            mounts={root: "/arkane"}, adapters=image.context["adapters"],
        ).stdout
    )
    payload = built["payload"]
    payload["literature"] = dict(cfg.get("literature") or DEFAULT_LITERATURE)
    src["ingestion"] = built["ingestion"]
    src["payload_counts"] = {
        key: len(payload.get(key) or []) for key in ("species", "transition_states", "micro_reactions", "states", "channels")
    }
    src["arkane_reference_rate"] = built["arkane_reference_rate"]
    src["payload_counts"]["channel_kinetics"] = len((payload.get("solve") or {}).get("channel_kinetics") or [])
    key = "paper-snapshot:pdep:" + str(payload.get("name") or "network")
    with session.client() as client:
        try:
            result = client.upload("network_pdep", payload, idempotency_key=key)
        except TCKDBError as exc:
            report.refuse(SOURCE, "network", exc)
            report.count(SOURCE, "uploads_refused")
            src["status"] = "refused"
            return
    collect_response_warnings(report, SOURCE, "network", result)
    report.count(SOURCE, "uploads_accepted")
    src["response"] = {k: v for k, v in (result or {}).items() if k != "warnings" and not isinstance(v, (list, dict))}
    src["status"] = "deposited"

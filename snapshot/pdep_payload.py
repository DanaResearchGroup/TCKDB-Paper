"""Build the N2H3 network's upload request from an Arkane run directory, in the pinned TCKDB image.

    python -m snapshot.pdep_payload /arkane

Run by ``source_pdep.py`` with the Arkane directory mounted read-only. Prints one JSON document: the
``NetworkPDepUploadRequest`` the PDep ingester (``backend/scripts/pdep_ingestion``, ``network_only=True``) builds, what
it could not carry over, and the rate of one channel at a reference point from the fit Arkane wrote to ``chem.inp``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

#: The channel and point the network's rate is read at, as ``(reactants, products, temperature K, pressure bar)``.
REFERENCE_POINT = (("NH3N",), ("N2H3",), 1000.0, 1.0)
ATM_PER_BAR = 1.0 / 1.01325


def chemkin_reference_rate(root: Path) -> dict[str, Any] | None:
    """k of the reference channel at the reference point, from the Chebyshev fit Arkane wrote to ``chem.inp``.

    ``chem.inp`` gives the fit's pressure domain in atm (CHEMKIN convention) and its coefficients rounded to four
    significant figures; the stored network carries the ``output.py`` fit. Returns ``None`` without a ``chem.inp``.
    """
    path = root / "chem.inp"
    if not path.is_file():
        return None
    from app.chemistry.network_kinetics_eval import evaluate_chebyshev
    from tckdb_chemkin.parser import parse_mechanism

    reactants, products, temperature, pressure = REFERENCE_POINT
    for reaction in parse_mechanism(path.read_text()).reactions:
        names = (tuple(sorted(n for _, n in reaction.reactants)), tuple(sorted(n for _, n in reaction.products)))
        if names != (tuple(sorted(reactants)), tuple(sorted(products))) or reaction.chebyshev is None:
            continue
        fit = reaction.chebyshev
        point = evaluate_chebyshev(
            temperature, pressure * ATM_PER_BAR, coefficients=fit.coefficients, tmin_k=fit.tmin, tmax_k=fit.tmax,
            pmin_bar=fit.pmin_atm, pmax_bar=fit.pmax_atm, stores_log10_k=True,
        )
        return {
            "channel": f"{' + '.join(reactants)} -> {' + '.join(products)}",
            "temperature_k": temperature,
            "pressure_bar": pressure,
            "k_from_chem_inp": point.k,
            "fit_line_in_chem_inp": reaction.line_no,
            "units": "s^-1 for a unimolecular channel, cm^3/(mol*s) for a bimolecular one (chem.inp)",
        }
    return None


def build(root: Path) -> dict[str, Any]:
    from scripts.pdep_ingestion.builder import build_network_pdep_payload

    payload, gap = build_network_pdep_payload(root, include_artifacts=False, network_only=True)
    ingestion = {
        "species_built": gap.species_built,
        "species_skipped": [list(item) for item in gap.species_skipped],
        "transition_states_with_geometry": gap.ts_built,
        "transition_states_without_geometry": gap.ts_stub_no_geometry,
        "rotor_treatment_unstated": gap.treatment_unstated,
        "micro_reactions": gap.micro_reactions,
        "channels_built": gap.channels_built,
        "channels_well_skipping": len(gap.channels_well_skipping),
        "unstorable_fields": gap.unstorable_fields,
    }
    return {"payload": payload, "ingestion": ingestion, "arkane_reference_rate": chemkin_reference_rate(root)}


if __name__ == "__main__":
    print(json.dumps(build(Path(sys.argv[1])), default=str))

# TCKDB-Paper

Code that builds the TCKDB paper's demonstration snapshot and computes the numbers the paper reports from it. The
snapshot is made the way any user would make one: data is deposited into a TCKDB instance through its public routes,
and the numbers are read back from that instance's database.

TCKDB itself is the `tckdb/` git submodule, pinned to one commit (see `pins.toml`).

## Layout

- `tckdb/`: the pinned TCKDB source (backend, schemas, Python client, CHEMKIN adapter, test fixtures).
- `pins.toml`: the TCKDB commit and its container image, the package versions at that commit, and the commits of
  `tckdb-adapters` and ARC the build uses.
- `snapshot/`: the snapshot build (sources, curation, export, comparison, read-back). See `snapshot/README.md`.
- `tckdb_paper_generators/`: one generator per reported number, and the registry that lists them. It is a deposit
  registry for TCKDB's publication deposit tools: `--generators tckdb_paper_generators.registry:GENERATORS`
  with `--generator-root` set to the root of this repository.
- `tests/`: unit tests for the generators and the snapshot scripts. `tests/conftest.py` loads TCKDB's database
  fixtures from the submodule.

## Set up

```bash
git clone --recurse-submodules https://github.com/DanaResearchGroup/TCKDB-Paper.git
cd TCKDB-Paper
```

Use TCKDB's backend environment (`tckdb/backend/environment.yml`, with the `[dev]` extra of `tckdb/backend`). Cantera
3.2.0 is part of it. A PostgreSQL server with the RDKit cartridge must be reachable; the image CI uses is
`informaticsmatters/rdkit-cartridge-debian:Release_2025_03_3`.

## Run the tests

```bash
export DB_USER=tckdb DB_PASSWORD=tckdb DB_HOST=127.0.0.1 DB_PORT=5432
python -m pytest tests -n 2
```

The tests create and drop their own `tckdb_test_*` databases.

## Build and check the snapshot

The build deposits four sources (the E2 conformer tree, ARC run folders, an Arkane directory and the formic acid
CHEMKIN model). Only the CHEMKIN model and the QCSchema fixture are in the `tckdb/` submodule; the other three are
read from paths set in the sources file, so the full build runs on a machine that holds them. Steps, outputs and
checks (two builds from empty instances compared, an archive restored and read back, the CHEMKIN export re-checked)
are in `snapshot/README.md`.

```bash
python snapshot/instance.py up --name a --port 8101
python snapshot/build.py --sources my_sources.yml --out-dir out_a
python snapshot/instance.py down --name a --drop
```

## Pinned versions

`pins.toml` is the record. A test checks that it agrees with the submodule.

## Licence

MIT, see `LICENSE`.

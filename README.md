# TCKDB-Paper

Code that builds the TCKDB paper's demonstration snapshot and computes the numbers the paper reports from it. The
snapshot is made the way any user would make one: data is deposited into a TCKDB instance through its public routes,
and the numbers are read back from that instance's database.

TCKDB itself is the `tckdb/` git submodule, pinned to one commit (see `pins.toml`). The code in `snapshot/`,
`tckdb_paper_generators/` and `tests/` came from TCKDB/TCKDB at commit 28c2c47, with its history.

## Layout

- `tckdb/`: the pinned TCKDB source (backend, schemas, Python client, test fixtures).
- `pins.toml`: the TCKDB commit and its container image, the package versions at that commit, and the commits of
  `tckdb-adapters` and ARC the build uses.
- `snapshot/`: the snapshot build (sources, curation, export, comparison, read-back). See `snapshot/README.md`.
- `tckdb_paper_generators/`: one generator per reported number, and the registry that lists them. It is a deposit
  registry for TCKDB's publication deposit tools: `--generators tckdb_paper_generators.registry:GENERATORS`
  with `--generator-root` set to the root of this repository.
- `tests/`: unit tests for the generators and the snapshot scripts. `tests/conftest.py` loads TCKDB's database
  fixtures from the submodule and the CHEMKIN and QCSchema adapters from the tckdb-adapters checkout.

## Set up

```bash
git clone --recurse-submodules https://github.com/DanaResearchGroup/TCKDB-Paper.git
cd TCKDB-Paper
```

Create an environment for this repository from TCKDB's backend environment file and install the submodule's packages
into it, the way CI does. Cantera 3.2.0 is part of the environment file. Use an environment of its own: the API writes
the installed `tckdb-backend` and `tckdb-schemas` versions into every release manifest, so an environment holding
another TCKDB checkout's install would misstate them. `snapshot/build.py` and `snapshot/instance.py up` refuse to run
when the installed `tckdb-backend`, `tckdb-client` or `tckdb-schemas` is not the version the submodule declares, and
`tests/test_pins.py` checks the same.

```bash
conda env create -n tckdb_paper_build -f tckdb/backend/environment.yml
conda activate tckdb_paper_build
python -m pip install -e tckdb/schemas/python/tckdb-schemas
python -m pip install -e "tckdb/backend[dev]"
python -m pip install -e tckdb/clients/python
python -c "import importlib.metadata as m; print(*(m.version(d) for d in ('tckdb-backend', 'tckdb-schemas', 'tckdb-client')))"
```

Run every command below in this environment. After moving the submodule to another commit, run the three installs
again.

The CHEMKIN and QCSchema adapters are not in TCKDB; they come from a git checkout of
[tckdb-adapters](https://github.com/calvinp0/tckdb-adapters) at the commit in `pins.toml`, imported from source (no
install). The tests find it through `TCKDB_ADAPTERS_ROOT`; the snapshot build through `adapter_path` in its sources
file (`snapshot/README.md`).

```bash
git clone https://github.com/calvinp0/tckdb-adapters.git ../tckdb-adapters
git -C ../tckdb-adapters checkout "$(python -c 'import tomllib; print(tomllib.load(open("pins.toml", "rb"))["tckdb_adapters"]["commit"])')"
export TCKDB_ADAPTERS_ROOT="$PWD/../tckdb-adapters"
```

`snapshot/build.py` stops if `app`, `tckdb_client` or `tckdb_schemas` is imported from outside `tckdb/`, or an adapter
from outside its `adapter_path`; `python -m tckdb_paper_generators.chemkin_export --check` (which takes
`--tckdb-root PATH` or `$TCKDB_ROOT` when the package is not beside `tckdb/`) stops if `app` is. A PostgreSQL server
with the RDKit cartridge must be reachable; the image CI uses is
`informaticsmatters/rdkit-cartridge-debian:Release_2025_03_3`.

## Run the tests

```bash
export DB_USER=tckdb DB_PASSWORD=tckdb DB_HOST=127.0.0.1 DB_PORT=5432
export TCKDB_ADAPTERS_ROOT=/path/to/tckdb-adapters
python -m pytest tests -n 2
```

The tests create and drop their own `tckdb_test_*` databases. Without `TCKDB_ADAPTERS_ROOT` they refuse to start, and
`tests/test_pins.py` checks that the checkout is at the pinned commit.

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

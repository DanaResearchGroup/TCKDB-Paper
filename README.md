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

TCKDB itself runs from the container image `pins.toml` names, by digest (`[tckdb].image` and `image_digest`): the API,
the migrations, the operator CLI, the archive tool and the expected-output generators all run in it (`snapshot/README.md`,
"How it runs"). Reproducing the numbers needs Docker, this repository and the archive (see "Reproduce" below).

The unit tests, and the host side of the build (the deposit clients, which talk to the API over HTTP), use a Python
environment of their own. Create it from TCKDB's backend environment file and install the submodule's packages into
it, the way CI does. Cantera 3.2.0 is part of the environment file. The tests check that the installed
`tckdb-backend`, `tckdb-client` and `tckdb-schemas` are the versions the submodule declares, and `snapshot/build.py`
refuses to run when the installed `tckdb-client` or `tckdb-schemas` is not (the client sends its installed version with
every request).

```bash
conda env create -n tckdb_paper_build -f tckdb/backend/environment.yml
conda activate tckdb_paper_build
python -m pip install -e tckdb/schemas/python/tckdb-schemas
python -m pip install -e "tckdb/backend[dev]"
python -m pip install -e tckdb/clients/python
python -c "import importlib.metadata as m; print(*(m.version(d) for d in ('tckdb-backend', 'tckdb-schemas', 'tckdb-client')))"
```

Run the tests and the build in this environment. After moving the submodule to another commit, run the three installs
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

The output holds the archive (`tckdb.archive`), the expected outputs, the CHEMKIN export, `build_report.json`,
`build_record.json` (which records the digest of the image the API ran) and the image itself,
`tckdb-api-<version>.tar.gz`, with its SHA-256 in `build_record.json` (`exports.image`).

## Reproduce

From the deposited archive and image, with Docker, a clone of this repository at the commit `build_record.json` names
(`source_commit.commit`, with its submodule) and a checkout of tckdb-adapters at `source_commit.tckdb_adapters_commit`.
No Python environment is built: `instance.py` and `compare.py` use only Python's standard library, and everything that
imports TCKDB runs in the image.

```bash
# 1. The image: load the deposited file (check its SHA-256 first), or pull the same digest.
sha256sum tckdb-api-0.4.0.tar.gz            # = build_record.json exports.image.sha256
docker load -i tckdb-api-0.4.0.tar.gz
docker pull laxzal/tckdb-api@sha256:519a48331a634ea244a9b7346be3500faee086dd80487873f516ed8ec4cfdfba   # or this

# 2. Postgres with the RDKit cartridge and an object store, from the submodule's compose file.
(cd tckdb && DB_PASSWORD=tckdb S3_SECRET_KEY=tckdb_secret docker compose up -d db seaweedfs)
export S3_ENDPOINT_URL=http://127.0.0.1:9000 S3_ACCESS_KEY=tckdb S3_SECRET_KEY=tckdb_secret

# 3. An empty instance from the image, and the archive restored into it.
python3 snapshot/instance.py up --name r --port 8110
python3 snapshot/instance.py restore --name r --archive /path/to/tckdb.archive

# 4. In the image, from the restored instance: the expected outputs regenerated, the archive exported again, and the
#    deposited CHEMKIN export checked against an in-process export of the same records.
IMAGE=laxzal/tckdb-api@sha256:519a48331a634ea244a9b7346be3500faee086dd80487873f516ed8ec4cfdfba
DEPOSITED=/path/to/deposited_output       # tckdb.archive, expected_outputs/, chemkin_export/
mkdir -p regenerated/expected_outputs
tckdb() {
  docker run --rm --network host --user "$(id -u):$(id -g)" --env HOME=/tmp \
    --volume "$PWD:/paper:ro" --volume /path/to/tckdb-adapters:/adapters:ro \
    --volume "$PWD/regenerated:/regenerated:rw" --volume "$DEPOSITED:/deposited:ro" \
    --env PYTHONPATH=/paper:/adapters/adapters/tckdb_chemkin:/adapters/adapters/tckdb_qcschema \
    --env DB_HOST=127.0.0.1 --env DB_PORT=5432 --env DB_USER=tckdb --env DB_PASSWORD=tckdb \
    --env DB_NAME=tckdb_test_snapshot_r --env S3_BUCKET=tckdb-test-snapshot-r --env S3_ENDPOINT_URL \
    --env S3_ACCESS_KEY --env S3_SECRET_KEY "$IMAGE" "$@"
}
ONLY=$(for f in "$DEPOSITED"/expected_outputs/*.json; do printf -- '--only %s ' "$(basename "$f" .json)"; done)
tckdb python scripts/ops/generate_expected_outputs.py --generators tckdb_paper_generators.registry:GENERATORS \
  --output-dir /regenerated/expected_outputs $ONLY      # the generators the deposited output holds
tckdb python scripts/tckdb_archive.py create /regenerated/tckdb.archive --overwrite
tckdb python -m tckdb_paper_generators.chemkin_export --check /deposited/chemkin_export --tckdb-root /app
cp -r "$DEPOSITED/chemkin_export" regenerated/

# 5. Compare with the deposited output (public refs, timestamps and the bucket name masked), then remove the instance.
python3 snapshot/compare.py "$DEPOSITED" regenerated
python3 snapshot/instance.py down --name r --drop
```

`compare.py` prints a JSON report and a `RESULT` line. The release manifest stored in the archive names the image's
`tckdb-backend` and `tckdb-schemas` versions and the database revision, so a restore into another TCKDB version shows
up there.

## Pinned versions

`pins.toml` is the record. A test checks that it agrees with the submodule.

## Licence

MIT, see `LICENSE`.

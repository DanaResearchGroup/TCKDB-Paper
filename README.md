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

On the host, `snapshot/build.py` imports only `tckdb_client`, `tckdb_schemas` and the adapters, never TCKDB's backend.
It stops if `tckdb_client` or `tckdb_schemas` is imported from outside `tckdb/`, if their installed versions are not the
submodule's, if an adapter is imported from outside `adapter_path`, or if the submodule or the adapters checkout is not
at the commit `pins.toml` names. `python -m tckdb_paper_generators.chemkin_export --check` (run in the image; it takes
`--tckdb-root PATH` or `$TCKDB_ROOT`) stops if `app` is imported from outside that root. A PostgreSQL server with the
RDKit cartridge must be reachable; the image CI uses is `informaticsmatters/rdkit-cartridge-debian:Release_2025_03_3`.

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

From the deposited output (`tckdb.archive`, `expected_outputs/`, `chemkin_export/`, `build_record.json`) and image,
with a clone of this repository at the commit `build_record.json` names (`source_commit.commit`, with its submodule) and
a checkout of tckdb-adapters at `source_commit.tckdb_adapters_commit`. No Python environment is built: `instance.py`,
`image.py` and `compare.py` use only the standard library, and everything that imports TCKDB runs in the image.

Host requirements: Docker on Linux (the containers use the host's network, `--network host`), Python 3.11 or later
(for `tomllib`), git and gzip.

The saved image, `tckdb-api-<version>.tar.gz`, holds one platform, the builder's: `build_record.json` names it
(`exports.image.platform`, `linux/amd64` for this deposit) with its manifest and config digests, which `pins.toml` also
lists (`[tckdb.image_platforms]`). On another platform pull the pinned index digest instead; `pins.toml` lists the
`linux/arm64` image as well. `snapshot/image.py` prints the reference the scripts run: the pinned digest when it is
present, else the loaded `laxzal/tckdb-api:<version>` when its digest is a pinned one for this host's platform. It pulls
only when neither is present.

```bash
set -euo pipefail

# 1. The image: load the deposited file (check its SHA-256 first), or pull the pinned digest on another platform.
sha256sum tckdb-api-0.4.0.tar.gz            # = build_record.json exports.image.sha256
docker load -i tckdb-api-0.4.0.tar.gz      # "Loaded image: laxzal/tckdb-api:0.4.0"
# docker pull laxzal/tckdb-api@sha256:519a48331a634ea244a9b7346be3500faee086dd80487873f516ed8ec4cfdfba
IMAGE=$(python3 snapshot/image.py)          # the local pinned copy; no pull when one is present

# 2. Postgres with the RDKit cartridge and an object store, from the submodule's compose file, once healthy.
(cd tckdb && DB_PASSWORD=tckdb S3_SECRET_KEY=tckdb_secret docker compose up -d --wait db seaweedfs)
export S3_ENDPOINT_URL=http://127.0.0.1:9000 S3_ACCESS_KEY=tckdb S3_SECRET_KEY=tckdb_secret

# 3. An empty instance from the image, and the archive restored into it.
python3 snapshot/instance.py up --name r --port 8110
python3 snapshot/instance.py restore --name r --archive /path/to/tckdb.archive

# 4. In the image, from the restored instance: the expected outputs regenerated, the archive exported again, and the
#    deposited CHEMKIN export checked against an in-process export of the same records.
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
tckdb python -m tckdb_paper_generators.chemkin_export --check /deposited/chemkin_export --tckdb-root /app \
  > regenerated/chemkin_export_check.json
python3 -c 'import json, sys; r = json.load(open(sys.argv[1])); print("CHEMKIN export:", r); sys.exit(not r["match"])' \
  regenerated/chemkin_export_check.json

# 5. Compare with the deposited output (public refs, timestamps and the bucket name masked), then remove the instance.
python3 snapshot/compare.py "$DEPOSITED" regenerated --without-chemkin-export
python3 snapshot/instance.py down --name r --drop
```

Step 4's export check must exit 0 and print `'match': True` with every file `same`: the saved `chem.inp`, `therm.dat`
and `manifest.json` (without its `generated_at`) equal, byte for byte, an export made in-process from the restored
database, and the saved request equals the one resolved from it. A mismatch exits 1 and names the file. The CHEMKIN
export is not regenerated as files, so step 5 leaves `chemkin_export/` out and says so; everything else it compares.
`compare.py` prints a JSON report and a `RESULT` line, `RESULT: no difference` when nothing differs. The release
manifest stored in the archive names the image's `tckdb-backend` and `tckdb-schemas` versions and the database
revision, so a restore into another TCKDB version shows up there.

The registry also holds `qcschema_interchange`, which is not part of the deposit: it needs `qcelemental`, which the
TCKDB image does not ship, and it reads TCKDB's committed QCSchema fixtures rather than the snapshot. The build lists
the generators it runs (`snapshot/build.py`, `EXPECTED_OUTPUTS`), and step 4 regenerates exactly those.

## Pinned versions

`pins.toml` is the record. A test checks that it agrees with the submodule.

## Licence

MIT, see `LICENSE`.

# DGI Food Access ETL

Python ETL pipeline that produces the bulk dataset for the [DGI Food Access dashboard](https://firststatelens.com/dgi-food-access/). Implementation tracks methodology v0.2.0 (definition-locked in the [private vault](https://github.com/scyfli/first-state-lens-vault) at session-09).

Authoritative design: `2026-05-11-DGI-Bulk-ETL-Design.md` in the vault `07-Briefs/`.

## Status

**S+3 (2026-05-11):** transforms layer complete. Population-weighted areal interpolation, SB 254-effective tract classification, food-resource universe merge, and the Frictionless datapackage writer all landed. `run_etl.py` orchestrates the full pipeline end-to-end and is exercised by a smoke-suite integration test (13 orchestrator tests).

- **S+1:** scaffold + 5 source pullers (USDA LILA, FirstMap SD2, DART GTFS, Census ACS, MMG)
- **S+2:** geocoding library (Census + Nominatim) + geocoding transform + manual-reviews second pass + DSB scaffold
- **S+3 (here):** transforms (apportion / sb254-effective / merge food resources) + Frictionless datapackage writer + per-resource schemas + end-to-end orchestrator
- **S+4 (next):** live-source orchestration + dashboard wire-up + methodology `publish: true` flip + first scheduled ETL run

## Layout

```
etl/
├── README.md                # this file
├── requirements.txt         # canonical pinned deps (per design brief)
├── parameters.yaml          # ETL parameters (thresholds, vintages, cadence)
├── manual-reviews.yaml      # human-confirmed tract assignments (audit trail)
├── run_etl.py               # top-level pipeline orchestrator (S+3 onward)
├── sources/                 # per-source pullers
├── transforms/              # geocode, apportion, sb254-effective, merge
├── outputs/                 # datapackage writer + per-resource schemas
├── lib/                     # shared infra: fetch, atomic IO, manifest, validate
├── tests/                   # pytest smoke tests + fixtures
└── raw/                     # pulled raw artifacts (gitignored)
```

`etl/lib/` is a documented extension of the brief's directory layout; the brief specifies data-flow modules (sources/transforms/outputs) and `lib/` carries shared infrastructure code those modules import.

## Local quickstart

```bash
# Lightweight install (everything except the geo stack)
python -m pip install requests pyyaml tenacity frictionless pytest

# Run smoke tests (offline; uses fixtures + skips geo-only tests when geopandas absent)
python -m pytest etl/tests/ -v

# Pull a single source live (requires network)
python -m etl.sources.usda_lila --out etl/raw/

# Full requirements (geopandas + tobler + pyproj + shapely; needed to run apportion + the geo path of run_etl)
python -m pip install -r etl/requirements.txt
```

**Note on Windows + heavy geo deps:** `geopandas`, `tobler`, `pyproj`, and `shapely` carry GDAL native bindings that can be painful to install on Windows. The transforms in `etl/transforms/apportion.py` import these lazily; tests that need them use `pytest.importorskip` so the smoke suite still runs on a Windows dev box (apportion tests skip cleanly). GitHub Actions Linux runners handle the full requirements cleanly and run every test.

## Running in CI

`.github/workflows/dgi-etl.yml` runs on:

- **Schedule:** first Sunday of each month at 09:00 UTC (data refresh)
- **Manual dispatch:** any pusher to the repo via the Actions UI
- **Pull requests** touching `etl/`: dry-run mode (smoke tests only, no committed outputs)

At S+3 the workflow still runs only the smoke-test job (with the full geo stack installed from `requirements.txt`, so every test — including the apportion suite — runs). Real data publication lands at S+4 when the live-source orchestration wires in and the methodology page flips `publish: true`.

## Methodology equivalences (R cite ↔ Python)

| Methodology cite (R) | Python equivalent | Used in |
|---|---|---|
| `tidycensus::interpolate_pw(extensive=TRUE)` | in-module population-weighted overlay built on `geopandas.overlay` (see [`apportion.py`](transforms/apportion.py)) | S+3 transform |
| `areal::aw_interpolate(weight="sum")` | same as above | S+3 transform |
| `tidycensus::get_acs(geography="tract")` | direct Census API via `requests` | S+1 puller (`census_acs.py`) |
| `sf::st_intersection`, `sf::st_distance` | `geopandas.GeoSeries.intersection / .distance` | S+3 transform |

`tobler.area_interpolate` is the PySAL implementation cited in the design brief; it does *area-weighted* (not population-weighted) interpolation. We import `tobler` for future refactors but the population-weighted variant lands in-module so the formula matches `tidycensus::interpolate_pw(extensive=TRUE)` exactly. The methodology page is not amended; this bridge lives in the design brief and this README.

## Open implementation questions (carried from design brief)

1. DPH My Healthy Community access pattern (S+4, pilot pull required)
2. DCFFP grantee list URL stability (S+4)
3. DSB grantee canonical URL (open since session-15; scaffold ships configurable)
4. Census ACS vintage selection (live puller documents the chosen vintage at run time)
5. Manual review volume threshold (revisit if `pending-manual-review` >20/cycle)
6. R2 migration trigger (output >100MB or refresh cadence demands cache invalidation)
7. DART GTFS canonical URL (S+1 puller verifies)
8. Block-group population pull (S+4) — `etl.transforms.sb254_effective` accepts block-group inputs but no puller produces them yet; live wire-in at S+4

---

*Part of First State Lens · FirmSide AI · Civic Analytics Lab*

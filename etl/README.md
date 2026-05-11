# DGI Food Access ETL

Python ETL pipeline that produces the bulk dataset for the [DGI Food Access dashboard](https://firststatelens.com/dgi-food-access/). Implementation tracks methodology v0.2.0 (definition-locked in the [private vault](https://github.com/scyfli/first-state-lens-vault) at session-09).

Authoritative design: `2026-05-11-DGI-Bulk-ETL-Design.md` in the vault `07-Briefs/`.

## Status

**S+5 (2026-05-11):** food-resource universe broadens + MMG apportionment unblocked. Three new pullers (TIGER counties → `mmg_counties_gdf` for the long-promised apportionment stage; SNAP retailers via FNS ArcGIS Hub; USDA farmers markets as a scaffold mirroring the DSB pattern). `etl/lib/load_raw.py` now feeds `food_resources_raw` from SNAP + farmers-markets outputs, so the merge stage's dedupe operates on real data instead of an empty list. Test suite at 156 passed / 2 skipped. Methodology unchanged at v0.2.1.

- **S+1:** scaffold + 5 source pullers (USDA LILA, FirstMap SD2, DART GTFS, Census ACS, MMG)
- **S+2:** geocoding library (Census + Nominatim) + geocoding transform + manual-reviews second pass + DSB scaffold
- **S+3:** transforms (apportion / sb254-effective / merge food resources) + Frictionless datapackage writer + per-resource schemas + end-to-end orchestrator
- **S+4:** TIGER tracts + TIGER BGs + Census ACS BG pullers; `etl/lib/load_raw.py` (disk → PipelineInputs); `run_etl.py` CLI flipped from scaffold to live orchestrator with `--pull` / `--strict` / `--dry-run`; `.github/workflows/dgi-etl.yml` `live-etl` job (schedule + workflow_dispatch); methodology version pin v0.2.0 → v0.2.1 (patch)
- **S+5 (here):** TIGER counties (`tiger_counties.py`, clipped to DE STATEFP=10) → `mmg_counties_gdf` populated; SNAP retailers (`snap_retailers.py`, ArcGIS query w/ pagination) → `food_resources_raw`; USDA farmers markets (`usda_farmers_markets.py` scaffold; canonical URL is a carried open question alongside DSB/MMG) → `food_resources_raw`. **session-18 Phase A** also patched DART GTFS URL drift (rotated path) + FirstMap SD2 URL drift (service retired → new `enterprise.firstmap.delaware.gov` Political Boundaries layer). MMG canonical URL documented as a carried open question.
- **S+6 (next):** per-tract demographics join (`acs-tract-demographics.csv` → TractInput poverty_rate + mfi) to certify SB 254 low-income tracts; USDA LILA xlsx → GeoJSON transform; DART GTFS shapes.txt → `dart-routes.geojson` transform; dashboard chart-data wire-up to `data/dgi-grants.csv` once DSB scraper has live data; MMG canonical CSV URL resolution; USDA AMS farmers-markets canonical URL resolution; methodology subdomain (`methodology.firststatelens.com`) via Quartz

## Layout

```
etl/
├── README.md                # this file
├── requirements.txt         # canonical pinned deps (per design brief)
├── parameters.yaml          # ETL parameters (thresholds, vintages, cadence)
├── manual-reviews.yaml      # human-confirmed tract assignments (audit trail)
├── run_etl.py               # top-level pipeline orchestrator + CLI (S+4 live)
├── sources/                 # per-source pullers (9 at S+4)
├── transforms/              # geocode, apportion, sb254-effective, merge
├── outputs/                 # datapackage writer + per-resource schemas
├── lib/                     # shared infra: fetch, atomic IO, manifest, validate, load_raw
├── tests/                   # pytest smoke tests + fixtures
└── raw/                     # pulled raw artifacts (gitignored)
```

S+5 sources catalog (12 pullers):

| Module | Output | Cadence | Notes |
|---|---|---|---|
| `etl/sources/usda_lila.py` | `usda-lila-raw.xlsx` | Annual | Food Access Research Atlas |
| `etl/sources/firstmap_sd2.py` | `firstmap-sd2.geojson` | Per redistricting | SD2 boundary (URL patched session-18: enterprise.firstmap.delaware.gov) |
| `etl/sources/dart_gtfs.py` | `dart-gtfs.zip` + `dart-stops.csv` | Quarterly | GTFS feed (URL patched session-18: /RiderInfo/Routes/ path) |
| `etl/sources/census_acs.py` | `acs-tract-de.json` | Annual | Tract-level ACS5 (pop, MFI, poverty, race) |
| `etl/sources/census_acs_bg.py` | `acs-bg-de.json` | Annual | S+4 — BG-level pop for SB 254 weighting |
| `etl/sources/mmg_food_insecurity.py` | `mmg-food-insecurity-counties.csv` | Annual | Map the Meal Gap (canonical URL is a carried open question) |
| `etl/sources/dsb_grants.py` | `dsb-grants.json` | Per-cycle | DGI grantee roster (URL-configurable; canonical is carried open question) |
| `etl/sources/tiger_tracts.py` | `tiger-tracts-de.zip` | Annual | S+4 — TIGER tract shapefile |
| `etl/sources/tiger_bgs.py` | `tiger-bgs-de.zip` | Annual | S+4 — TIGER block-group shapefile |
| `etl/sources/tiger_counties.py` | `tiger-counties-us.zip` | Annual | **S+5** — national TIGER counties; clipped to DE downstream → `mmg_counties_gdf` |
| `etl/sources/snap_retailers.py` | `snap-retailers-de.geojson` | Weekly | **S+5** — USDA FNS ArcGIS Hub w/ pagination |
| `etl/sources/usda_farmers_markets.py` | `usda-farmers-markets-de.json` | Quarterly | **S+5 scaffold** — USDA AMS endpoints have access friction (carried open question) |

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

# End-to-end live pipeline (pulls every source; writes dgi-food-access/data/)
python -m etl.run_etl --pull --strict

# Or: just compose from already-pulled raws in etl/raw/
python -m etl.run_etl --raw-dir etl/raw --output-dir dgi-food-access/data

# Inspect-only (no outputs written)
python -m etl.run_etl --dry-run
```

**Note on Windows + heavy geo deps:** `geopandas`, `tobler`, `pyproj`, and `shapely` carry GDAL native bindings that can be painful to install on Windows. The transforms in `etl/transforms/apportion.py` import these lazily; tests that need them use `pytest.importorskip` so the smoke suite still runs on a Windows dev box (apportion tests skip cleanly). GitHub Actions Linux runners handle the full requirements cleanly and run every test.

## Running in CI

`.github/workflows/dgi-etl.yml` runs two jobs:

1. **`smoke-tests`** — offline; full requirements install + pytest. Runs on every push, PR, schedule, and dispatch.
2. **`live-etl`** — pulls every external source and runs the full pipeline. Triggered by the monthly schedule (`0 9 1-7 * 0`) and by `workflow_dispatch`. Uploads `dgi-food-access/data/` as an artifact every time. When `workflow_dispatch.commit_data == true`, commits `dgi-food-access/data/` back to `main` so the dashboard picks it up on the next Worker deploy.

Trigger a live data refresh from the Actions tab → "DGI ETL" → "Run workflow":

- `reason` (free text) — recorded in the commit message
- `live_run` (default: `true`) — runs the `live-etl` job
- `commit_data` (default: `false`) — commits refreshed data back to `main`

`CENSUS_API_KEY` is read from repo secrets and passed to the Census pullers (keyless requests work for low volume; the key removes rate-limit friction on scheduled refreshes).

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

# DGI Food Access ETL

Python ETL pipeline that produces the bulk dataset for the [DGI Food Access dashboard](https://firststatelens.com/dgi-food-access/). Implementation tracks methodology v0.2.0 (definition-locked in the [private vault](https://github.com/scyfli/first-state-lens-vault) at session-09).

Authoritative design: `2026-05-11-DGI-Bulk-ETL-Design.md` in the vault `07-Briefs/`.

## Status

**S+1 (this session, 2026-05-11):** skeleton + first source pullers (USDA LILA, FirstMap SD2, DART GTFS, Census ACS, MMG). Pullers download raw artifacts to `etl/raw/` (gitignored). Smoke tests use fixtures, not live network.

Subsequent sessions: S+2 geocoding + DSB scraper; S+3 transforms + apportionment; S+4 dashboard wire-up + methodology `publish: true` flip.

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
# S+1 lightweight install (no geo libs needed for pullers yet)
python -m pip install requests pyyaml tenacity frictionless pytest

# Run smoke tests (offline; uses fixtures)
python -m pytest etl/tests/ -v

# Pull a single source live (requires network)
python -m etl.sources.usda_lila --out etl/raw/

# Full requirements (needed for transforms in S+3 onward)
python -m pip install -r etl/requirements.txt
```

**Note on Windows + heavy geo deps:** `geopandas`, `tobler`, `pyproj`, and `shapely` carry GDAL native bindings that can be painful to install on Windows. For S+1 these aren't required (pullers use only `requests` + stdlib). GitHub Actions Linux runners handle the full requirements cleanly; local dev on Windows can stay on the lightweight subset until transforms work begins.

## Running in CI

`.github/workflows/dgi-etl.yml` runs on:

- **Schedule:** first Sunday of each month at 09:00 UTC (data refresh)
- **Manual dispatch:** any pusher to the repo via the Actions UI
- **Pull requests** touching `etl/`: dry-run mode (smoke tests only, no committed outputs)

At S+1 the workflow only runs smoke tests. Real data publication lands at S+4 when transforms are complete and the methodology page flips `publish: true`.

## Methodology equivalences (R cite ↔ Python)

| Methodology cite (R) | Python equivalent | Used in |
|---|---|---|
| `tidycensus::interpolate_pw(extensive=TRUE)` | `tobler.area_interpolate(extensive=True)` | S+3 transform |
| `areal::aw_interpolate(weight="sum")` | `tobler.area_interpolate(extensive=True)` | S+3 transform |
| `tidycensus::get_acs(geography="tract")` | direct Census API via `requests` | S+1 puller (`census_acs.py`) |
| `sf::st_intersection`, `sf::st_distance` | `geopandas.GeoSeries.intersection / .distance` | S+3 transform |

The methodology page is not amended; this bridge lives in the design brief and this README.

## Open implementation questions (carried from design brief)

1. DPH My Healthy Community access pattern (S+2, pilot pull required)
2. DCFFP grantee list URL stability (S+2)
3. DSB grantee page parse strategy (S+2; tolerant parser + snapshot diff)
4. Census ACS vintage selection (S+1 puller will document the chosen vintage)
5. Manual review volume threshold (revisit if `pending-manual-review` >20/cycle)
6. R2 migration trigger (output >100MB or refresh cadence demands cache invalidation)
7. DART GTFS canonical URL (S+1 puller verifies)

---

*Part of First State Lens · FirmSide AI · Civic Analytics Lab*

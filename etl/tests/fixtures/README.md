# Test fixtures

Toy data for offline smoke tests. The shape and column names mirror the
real upstream payloads at small scale (2 counties / 5 tracts) so transforms
can be exercised without network or full-DE data volumes.

## Files

| File | Shape | Used by |
|---|---|---|
| `sd2-toy.geojson` | 1-feature FeatureCollection (Senate District 2 polygon) | FirstMap SD2 puller validate test |
| `mmg-toy.csv` | 3 DE county rows with FIPS, Year, Overall Food Insecurity Rate | MMG puller validate test; S+3 apportionment fixture |
| `acs-toy.json` | Census-API-shaped JSON: header row + 2 tract rows | Census ACS puller fixture; S+3 join test |

Adding a fixture: keep it small (<5KB), DE-shaped, and column-aligned with
the real upstream. Document here. No live data is committed.

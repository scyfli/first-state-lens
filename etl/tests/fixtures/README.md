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

## Candidate list fixtures (added 2026-10-05)

- `de_candidates_2026-10-05.html`: the Department of Elections "Filed Candidates by Office" page from 2026-10-05 (about 136 KB, larger than the usual fixture budget because the parser has to see the whole table). Every candidate's contact block is replaced with `[REDACTED]` values under the original labels. Names, offices, parties, statuses, filing dates and campaign websites are the public listing as published. No real addresses, phone numbers or emails are in this repo.
- `de_candidates_shapes.html`: three synthetic rows ("Test Candidate ...", example.org, 555 numbers, made-up streets) reproducing the live contact-cell layouts (Mailing Address, PO Box, Phone #2, Email #2, empty cell, withdrawn row) so the tests prove every contact field is dropped.

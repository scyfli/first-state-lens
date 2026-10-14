# Wiring: water-rebuild (Y2)

Branch `feat/water-rebuild`. The builder did not edit any shared file. Trazyn wires these.

## What the branch adds

- `etl/sources/epa_sdwis_systems.py`: a new puller. It writes `water/data/water-systems.json` and `water/data/water-systems-manifest.json`.
- `etl/pages/water_pages.py`: a generator. It writes `water/index.html` (now static) and 463 pages at `water/system/<pwsid>/`. It removes stale system folders. With `--sitemap` it also fills a marker block in `sitemap.xml`.
- Tests: `etl/tests/test_epa_sdwis_systems.py`, `etl/tests/test_water_pages.py`, and the fixture `etl/tests/fixtures/epa_sdwis_systems.json`. The fixture's contact fields are fake placeholders.
- `etl/sources/epa_sdwa_de.py` and `water/data/water-summary.json` are unchanged. The new index reads only `lead_note` from that file and prints it word for word.

## sitemap.xml

1. Change the existing `/water/` line's lastmod to the data date:
   ```
   <url><loc>https://firststatelens.com/water/</loc><lastmod>2026-10-14</lastmod><priority>0.8</priority></url>
   ```
2. Directly below it, add the marker pair once:
   ```
   <!-- WATER:START -->
   <!-- WATER:END -->
   ```
3. Run `python3 -m etl.pages.water_pages --sitemap`. That writes 463 lines of this form between the markers, sorted by path, with lastmod set to `data_as_of`:
   ```
   <url><loc>https://firststatelens.com/water/system/de0000263/</loc><lastmod>2026-10-14</lastmod><priority>0.6</priority></url>
   ```
   Without the markers, the flag does nothing.

## llms.txt

Replace the current water line with:
```
- [Is My Water Safe?](https://firststatelens.com/water/): Find your Delaware public water system and read its EPA drinking water violation record, with one page per system (dates, rule names, health-based flags, return-to-compliance dates). Source: EPA SDWIS.
- [Example water system page](https://firststatelens.com/water/system/de0000263/): One page per Delaware public water system at /water/system/<pwsid>/. Source: EPA SDWIS.
```

## scripts/a11y-audit.js ROUTES

`/water/` is already in the list. Add one route for the system template:
```
'/water/system/de0000263/'
```

## .github/workflows/refresh-all.yml

- In "Run all dashboard pullers", after the `Water` line:
  ```
  run "WaterSystems" etl.sources.epa_sdwis_systems --out water/data
  run "WaterPages"   etl.pages.water_pages --sitemap
  ```
  `run` calls `python -m "$@"`, so both lines work as written. Put `WaterPages` after `WaterSystems`.
- Artifact path: `water/data/` already covers the new JSON files.
- `git add` line: add `water/index.html water/system sitemap.xml`.
- A weekly run with no change in EPA's data leaves every file the same: `data_as_of` moves only when the content changes. The manifest's `generated_at` changes on every run, like the other manifests.

## Homepage card (optional copy fix, not a new dashboard)

The card in `index.html` says "1,344 systems" and "with each system's current compliance status". The correct Delaware count is 1,362. Suggested:
```
<div class="card-description">
  Find your Delaware public water system and read its EPA drinking water record: every violation, its dates,
  and whether the state recorded it as resolved. One page per system.
</div>
...
<span class="card-meta-pill">1,362 systems</span>
```

## .assetsignore

No change.

## Finding: the old puller's Delaware filter is wrong (Mark/Trazyn call)

`epa_sdwa_de.py` (which feeds `water-summary.json`) uses `WATER_SYSTEM/STATE_CODE/DE JOIN VIOLATION`. Checked live on 2026-10-14:

- `WATER_SYSTEM.STATE_CODE` is the state of the mailing address. The STATE_CODE=DE set includes 91 out-of-state systems (Maryland 50, Pennsylvania 17, and others) and leaves out 110 Delaware systems.
- The join returns 789 rows. 56 of them belong to out-of-state systems. It drops 1,033 of Delaware's 1,766 violations, including some for systems that are in the STATE_CODE=DE set (for example, DE0000590 has 50 violations and none appear in the join).
- `PRIMACY_AGENCY_CODE=DE` and `PWSID BEGINNING DE` return the same 1,766 violation ids. Per-PWSID counts match direct lookups. The new puller uses PRIMACY_AGENCY_CODE=DE and checks on every run that the two filters agree.
- The live page currently says 789 violations, 434 health-based, 0 open, and "No violations are currently open". The corrected figures are 1,766 violations, 687 health-based, and 101 with no return-to-compliance date.

The rebuilt `/water/` shows the corrected figures, so the published numbers change in this release. That is a factual correction. The old puller is left as it was, so it stays in the weekly run until you choose to drop it or fix it. Only its `lead_note` is still read.

## Stretch: water service areas (CPCN)

A public, keyless layer exists: FirstMap `https://enterprise.firstmap.delaware.gov/arcgis/rest/services/Boundaries/DE_CPCN/FeatureServer`. Layer 0 is "Water CPCN" (1,286 polygons; fields COMPANY1, SERVICE_A, CPCN_, COUNTY, ISSUE_DATE). The Public Service Commission maintains it. It has no PWSID, so matching it to SDWIS systems would mean matching names. It covers only utilities the PSC regulates, so municipal systems such as Wilmington, Newark and Dover are not in it. No address lookup was built.

# Wiring: roads-contracts (Y8 road safety, Y9 state contracts tab)

Branch `feat/roads-contracts`. Shared files are NOT edited on this branch; apply the lines below when integrating.

## Y8: `/road-safety/` (new top-level dashboard)

Source: DSHS Public Crash Data, data.delaware.gov `827n-m6xc` (monthly, about the 5th; crashes 2009 through about six months back). Rows updated 2026-10-05; data through 2026-03-31.

### sitemap.xml

```xml
  <url><loc>https://firststatelens.com/road-safety/</loc><lastmod>2026-10-05</lastmod><priority>0.8</priority></url>
```

### llms.txt (Dashboards list)

```markdown
- [Delaware Crashes by County and Month](https://firststatelens.com/road-safety/): Crash reports in Delaware by county and month since January 2009, in the state's own classifications (non-reportable, property damage only, personal injury, fatality). Counts of crashes, not people. Source: Delaware Department of Safety and Homeland Security public crash data.
```

### scripts/a11y-audit.js ROUTES

Add `'/road-safety/'`.

### index.html homepage card (copy of the Reassessment card markup)

```html
    <a href="/road-safety/" class="dashboard-card" style="--card-accent:#22d3ee">
      <div class="card-header">
        <div class="card-title">Crashes by County and Month</div>
        <div class="card-status">Live</div>
      </div>
      <div class="card-tagline">Delaware · Road safety</div>
      <div class="card-description">
        Every crash report in the state's public crash data since 2009, counted by county, month and the
        state's own classification. Counts of crashes, not people; no individual crash records.
      </div>
      <div class="card-meta-row">
        <span class="card-meta-pill">DSHS crash data</span>
        <span class="card-meta-pill">Through March 2026</span>
        <span class="card-meta-pill">588,486 reports</span>
      </div>
      <span class="card-enter">Enter dashboard</span>
    </a>
```

## Y9: Contracts section on `/spending/` (no new route)

Source: OMB Government Support Services, Statewide Central Contract Spend, data.delaware.gov `sifm-293u` (monthly, public domain). Rows updated 2026-09-16; spend July 2022 to July 2026. The section sits between `<!-- CONTRACTS:START` and `<!-- CONTRACTS:END -->` in `spending/index.html`, anchor `#contracts`; its CSS is appended to the page's head `<style>`. Existing page copy is unchanged (diff is insertions only).

### sitemap.xml

Bump the existing `/spending/` `<lastmod>` to `2026-09-16` (no new URL).

### llms.txt

Append to the existing spending line, or add:

```markdown
- [Delaware Statewide Central Contracts](https://firststatelens.com/spending/#contracts): Spend reported against the statewide central contracts run by Government Support Services, by contract and vendor, for the latest fiscal year that has ended. Source: OMB Government Support Services, Statewide Central Contract Spend.
```

### a11y ROUTES

`/spending/` is already covered.

## refresh-all.yml (both items)

Run lines (puller first, then its page generator; the generators read the JSON the pullers just wrote):

```bash
          run "RoadSafety"      etl.sources.de_crashes --out road-safety/data
          run "RoadSafetyPage"  etl.pages.road_safety_page
          run "Contracts"       etl.sources.de_contract_spend --out spending/data
          run "ContractsPage"   etl.pages.contracts_section
```

If a puller fails, its page step re-renders from the last committed JSON (no change), so it is safe to run unconditionally.

Artifact `path:` additions:

```
            road-safety/data/
            road-safety/index.html
            spending/index.html
```

(`spending/data/` is already listed.)

`git add` additions:

```
road-safety/data road-safety/index.html spending/index.html
```

## .assetsignore

No change. The JSON under `road-safety/data/` and `spending/data/contracts-*.json` is meant to be public (linked from the pages as the data download).

## Files on the branch

- `etl/lib/socrata.py` (shared polite Socrata client: UA, 2 s spacing, retries, SoQL-error raise)
- `etl/sources/de_crashes.py`, `etl/pages/road_safety_page.py`, `road-safety/index.html`, `road-safety/data/{crashes-summary.json,manifest.json}`
- `etl/sources/de_contract_spend.py`, `etl/pages/contracts_section.py`, `spending/index.html` (section + CSS added), `spending/data/{contracts-summary.json,contracts-manifest.json}` (named so the Checkbook `manifest.json` is never overwritten)
- Tests: `etl/tests/test_de_crashes.py`, `etl/tests/test_de_contract_spend.py`, `etl/tests/html_balance.py`, fixtures `etl/tests/fixtures/de_crashes_*.json`, `etl/tests/fixtures/de_contract_spend_*.json` (aggregates only; every fixture vendor is a business)

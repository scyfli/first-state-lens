# Wiring: bill-tracker-full (Y5, full-session bill tracker)

Branch `feat/bill-tracker-full`. Shared files are NOT edited on the branch; add these lines when integrating.

## What moved

- The SB 272 single-bill tracker moved from `/bill-tracker/` to **`/bill-tracker/sb-272/`** (file `bill-tracker/sb-272/index.html`). Published copy is unchanged. Only these changed: canonical, `og:url` and JSON-LD `url` now point at `/bill-tracker/sb-272/`; the data fetch is now absolute (`/bill-tracker/data/bill.json`, the file `bill-tracker-etl.yml` still writes); one footer link was added ("Every bill this session").
- `/bill-tracker/` is now the session index (every bill in the 153rd General Assembly). Anyone with an old link to `/bill-tracker/` lands on the index, which links to the SB 272 page in its "One bill in more detail" section. **Lead decides** whether that link is enough or SB 272 deep links need more (there is no redirect; a redirect would break the index).
- The old page's title and meta keep their pre-existing em dashes (published copy, not reworded per B10).

## sitemap.xml

Replace the existing `/bill-tracker/` line and add the SB 272 page:

```xml
  <url><loc>https://firststatelens.com/bill-tracker/</loc><lastmod>2026-10-14</lastmod><priority>0.7</priority></url>
  <url><loc>https://firststatelens.com/bill-tracker/sb-272/</loc><lastmod>2026-10-14</lastmod><priority>0.5</priority></url>
```

## llms.txt

Replace the current SB 272 line with:

```
- [Every bill in Delaware's 153rd General Assembly](https://firststatelens.com/bill-tracker/): Every bill, substitute and resolution in the 2025 to 2026 session, with title, primary sponsor, status and last action in the legislature's own words. In bill number order; no picks. Source: legis.delaware.gov. Data: https://firststatelens.com/bill-tracker/data/bills-153.json
- [Tracking Delaware Senate Bill 272](https://firststatelens.com/bill-tracker/sb-272/): A single-bill tracker: status, sponsors, action timeline, and the recorded vote. Source: Open States.
```

## scripts/a11y-audit.js ROUTES

`'/bill-tracker/'` is already in ROUTES (now the index template). Add the moved page:

```js
'/bill-tracker/sb-272/'
```

If a later run splits the index (page over 1.5 MB), also add one group template, e.g. `'/bill-tracker/house-bills/'`.

## Homepage card (`index.html`)

The existing card at `href="/bill-tracker/"` now describes the wrong page. Suggested replacement (same markup as the current card); also update the JSON-LD Dataset entry for `/bill-tracker/` around line 433:

```html
    <a href="/bill-tracker/" class="dashboard-card" style="--card-accent:#d8a13a">
      <div class="card-header">
        <div class="card-title">Every bill this session</div>
        <div class="card-status">Live</div>
      </div>
      <div class="card-tagline">legis.delaware.gov · 153rd General Assembly</div>
      <div class="card-description">
        Every bill, substitute and resolution in the 2025 to 2026 session, with its status and last action in
        the legislature's own words. Sort by number or date, filter by any word. SB 272 keeps its own page.
      </div>
      <div class="card-meta-row">
        <span class="card-meta-pill">legis.delaware.gov</span>
        <span class="card-meta-pill">1,484 items</span>
        <span class="card-meta-pill">updated weekly</span>
      </div>
      <span class="card-enter">Enter dashboard</span>
    </a>
```

JSON-LD entry: `{ "@type": "Dataset", "name": "Every bill in Delaware's 153rd General Assembly", "url": "https://firststatelens.com/bill-tracker/", "description": "Every bill, substitute and resolution in the 2025 to 2026 Delaware General Assembly: title, primary sponsor, status and last action, from legis.delaware.gov." }`

## Refresh workflow

The puller is keyless (official legislature JSON). Run it, then the page generator:

```bash
run "Bills"     etl.sources.de_legis_bills --out bill-tracker/data
run "BillsPage" etl.pages.bill_tracker_pages
```

- Artifact path: `bill-tracker/data/` and `bill-tracker/index.html` (plus `bill-tracker/*-bills/`, `bill-tracker/*-resolutions/` if it ever splits).
- `git add` paths: `bill-tracker/data bill-tracker/index.html` (and the group folders if split).
- **Runtime:** the first run reads every action log, about 1,580 requests at one per 2 s (about an hour). Later runs read only new bills, bills whose status changed, and bills with activity in the last 45 days, so out of session a run is about 4 minutes (99 listing pages). `refresh-all.yml` has `timeout-minutes: 30`; mid-session weekly runs may need more. Recommended: give this puller its own weekly job (or step) with `timeout-minutes: 90`, and run it once a month with `--full` so long-quiet bills get their action log re-read.
- `bill-tracker-etl.yml` (daily, SB 272) runs `git add bill-tracker/data/`, which would also pick up any change to `bills-153*.json`. Harmless, but note it.

## Rolling to the 154th General Assembly (convenes 2027-01-12)

Change `CURRENT_SESSION = 153` to `154` in `etl/sources/de_legis_bills.py` (the generator reads the same constant). Run once with `--min-rows 1` if the 154th has fewer items than the 153rd floor; the 153rd floor (`EXPECTED_FLOOR`) does not apply to 154. Output becomes `bill-tracker/data/bills-154.json`; `bills-153.json` stays as the archive. Update the sitemap/llms/card copy that names the 153rd.

## .assetsignore

No additions. `bill-tracker/data/*.json` is meant to be public (the page links to it as a download).

# Wiring: Delaware Office Registry (Y1), branch `feat/office-registry`

Pages: `/offices/` plus `/offices/federal/`, `/offices/statewide/`, `/offices/general-assembly/`,
`/offices/new-castle-county/`, `/offices/kent-county/`, `/offices/sussex-county/`, `/offices/school-boards/`.
Data: `offices/data/registry.json` (hand-curated, checked 2026-10-14). There is no puller.

Rebuild after any edit to the registry:

```
python3 -m etl.office_registry          # validator, exit 1 on any error
python3 -m etl.pages.office_pages       # validates again, then writes the 8 pages (write-if-changed)
python3 -m pytest etl/tests/test_office_registry.py etl/tests/test_office_pages.py -q
```

The validator cross-checks `candidates/data/ballot-2026.json`: every 2026 race must map to a registry entry
and every registry seat with next election 2026 must link to an existing race path. If the daily candidates job
ever adds or renames a race path, `python3 -m etl.office_registry` fails until the registry is updated.

## sitemap.xml (add after the reassessment line, outside the BALLOT markers)

```
  <url><loc>https://firststatelens.com/offices/</loc><lastmod>2026-10-14</lastmod><priority>0.8</priority></url>
  <url><loc>https://firststatelens.com/offices/federal/</loc><lastmod>2026-10-14</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/offices/statewide/</loc><lastmod>2026-10-14</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/offices/general-assembly/</loc><lastmod>2026-10-14</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/offices/new-castle-county/</loc><lastmod>2026-10-14</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/offices/kent-county/</loc><lastmod>2026-10-14</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/offices/sussex-county/</loc><lastmod>2026-10-14</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/offices/school-boards/</loc><lastmod>2026-10-14</lastmod><priority>0.6</priority></url>
```

## llms.txt (next to the candidates lines)

```
- [Delaware Office Registry](https://firststatelens.com/offices/): Every elected office in Delaware from U.S. Senate to county row offices and school boards, with term length, current holder, party label, and last and next regular election, each linked to an official source (official office pages, the Delaware Constitution and Code, Department of Elections candidate lists). Pages per level, for example https://firststatelens.com/offices/general-assembly/.
- [Delaware School Boards](https://firststatelens.com/offices/school-boards/): Every public school district board in Delaware: seats, term, May election rule, next election year, and a link to the district's board page. Vocational-technical boards are appointed by the Governor.
```

## scripts/a11y-audit.js ROUTES (two templates: index, level page, plus the school-board table)

```
'/offices/', '/offices/general-assembly/', '/offices/school-boards/'
```

Also add `- "offices/**"` to both path lists in `.github/workflows/a11y.yml` (next to `reassessment/**`).

## Homepage card (`index.html`, copy of the reassessment card markup)

```html
    <a href="/offices/" class="dashboard-card" style="--card-accent:#818cf8">
      <div class="card-header">
        <div class="card-title">Delaware Office Registry</div>
        <div class="card-status">Live</div>
      </div>
      <div class="card-tagline">Statewide · Who holds each office</div>
      <div class="card-description">
        Every elected office from U.S. Senate to county row offices and school boards: what it does, the term,
        who holds it today and the next regular election. Each holder links to the official page it came from.
      </div>
      <div class="card-meta-row">
        <span class="card-meta-pill">Official office pages</span>
        <span class="card-meta-pill">Delaware Code</span>
        <span class="card-meta-pill">109 offices · 19 boards</span>
      </div>
      <span class="card-enter">Enter dashboard</span>
    </a>
```

## refresh-all.yml

No puller, so no `run` line, artifact path or `git add` entry. Recommended (optional): a CI step
`python3 -m etl.office_registry` in the job that runs `candidates-daily.yml`, so a ballot change that breaks
the registry's 2026 links is caught the same day.

## .assetsignore

Nothing new. `etl/` and `docs/` are already ignored. `offices/data/registry.json` is meant to be public
(candidate pages will read it).

## Not wired on purpose

- No election deadline banner: these are reference pages, not election pages.
- The registry must be re-checked after the Nov 3 general election (E5): 2026 seats change holders in
  January 2027 (federal Jan 3; state and county offices per their own start dates).

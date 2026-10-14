# Wiring: restaurant inspections (Y7)

Branch `feat/inspections`. The builder did not touch any shared file. Trazyn applies the items below.

## 1. sitemap.xml

Add a marker block once, just before `</urlset>`. After that, `etl/pages/inspection_pages.py` rewrites the block on every run, so town pages that are added, split or dropped stay in sync. It uses the state's own update date as `lastmod`, so a refresh with no data change leaves the sitemap unchanged.

```
  <!-- INSPECTIONS:START -->
  <!-- INSPECTIONS:END -->
```

Then run `python3 -m etl.pages.inspection_pages`. It fills in these 57 lines (as of state data 2026-10-09):

```
  <url><loc>https://firststatelens.com/inspections/</loc><lastmod>2026-10-09</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/inspections/bear/</loc><lastmod>2026-10-09</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/inspections/bethany-beach/</loc><lastmod>2026-10-09</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/inspections/bridgeville/</loc><lastmod>2026-10-09</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/inspections/camden-wyoming/</loc><lastmod>2026-10-09</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/inspections/camden/</loc><lastmod>2026-10-09</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/inspections/cheswold/</loc><lastmod>2026-10-09</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/inspections/claymont/</loc><lastmod>2026-10-09</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/inspections/clayton/</loc><lastmod>2026-10-09</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/inspections/dagsboro/</loc><lastmod>2026-10-09</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/inspections/delaware-city/</loc><lastmod>2026-10-09</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/inspections/delmar/</loc><lastmod>2026-10-09</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/inspections/dewey-beach/</loc><lastmod>2026-10-09</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/inspections/dover/</loc><lastmod>2026-10-09</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/inspections/ellendale/</loc><lastmod>2026-10-09</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/inspections/elsmere/</loc><lastmod>2026-10-09</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/inspections/farmington/</loc><lastmod>2026-10-09</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/inspections/felton/</loc><lastmod>2026-10-09</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/inspections/fenwick-island/</loc><lastmod>2026-10-09</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/inspections/frankford/</loc><lastmod>2026-10-09</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/inspections/frederica/</loc><lastmod>2026-10-09</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/inspections/georgetown/</loc><lastmod>2026-10-09</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/inspections/greenville/</loc><lastmod>2026-10-09</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/inspections/greenwood/</loc><lastmod>2026-10-09</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/inspections/harbeson/</loc><lastmod>2026-10-09</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/inspections/harrington/</loc><lastmod>2026-10-09</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/inspections/hartly/</loc><lastmod>2026-10-09</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/inspections/hockessin/</loc><lastmod>2026-10-09</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/inspections/houston/</loc><lastmod>2026-10-09</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/inspections/laurel/</loc><lastmod>2026-10-09</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/inspections/lewes/</loc><lastmod>2026-10-09</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/inspections/lincoln/</loc><lastmod>2026-10-09</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/inspections/little-creek/</loc><lastmod>2026-10-09</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/inspections/magnolia/</loc><lastmod>2026-10-09</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/inspections/marydel/</loc><lastmod>2026-10-09</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/inspections/middletown/</loc><lastmod>2026-10-09</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/inspections/milford/</loc><lastmod>2026-10-09</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/inspections/millsboro/</loc><lastmod>2026-10-09</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/inspections/millville/</loc><lastmod>2026-10-09</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/inspections/milton/</loc><lastmod>2026-10-09</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/inspections/new-castle/</loc><lastmod>2026-10-09</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/inspections/newark/</loc><lastmod>2026-10-09</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/inspections/newport/</loc><lastmod>2026-10-09</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/inspections/ocean-view/</loc><lastmod>2026-10-09</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/inspections/odessa/</loc><lastmod>2026-10-09</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/inspections/peipsic/</loc><lastmod>2026-10-09</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/inspections/port-penn/</loc><lastmod>2026-10-09</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/inspections/rehoboth-beach/</loc><lastmod>2026-10-09</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/inspections/seaford/</loc><lastmod>2026-10-09</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/inspections/selbyville/</loc><lastmod>2026-10-09</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/inspections/smyrna/</loc><lastmod>2026-10-09</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/inspections/stanton/</loc><lastmod>2026-10-09</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/inspections/townsend/</loc><lastmod>2026-10-09</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/inspections/wilmington/</loc><lastmod>2026-10-09</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/inspections/wilmington/u-to-z/</loc><lastmod>2026-10-09</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/inspections/woodside/</loc><lastmod>2026-10-09</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/inspections/wyoming/</loc><lastmod>2026-10-09</lastmod><priority>0.6</priority></url>
```

## 2. llms.txt

```
- [Delaware Restaurant Inspections](https://firststatelens.com/inspections/): Food establishment inspection violations by establishment and date, in the state's own words, with one page per town. No grades or scores; a violation is not a closure. Source: Delaware Division of Public Health, Office of Food Protection (data.delaware.gov 384s-wygj).
```

## 3. scripts/a11y-audit.js ROUTES

Add one route per template:

```
'/inspections/', '/inspections/wilmington/'
```

`/inspections/wilmington/` is the largest page (about 910 KB). If CI time matters, `/inspections/newark/` (382 KB) uses the same template.

## 4. Homepage card (index.html)

This is a new top-level dashboard. Copy of the existing card markup:

```html
    <a href="/inspections/" class="dashboard-card" style="--card-accent:#22d3ee">
      <div class="card-header">
        <div class="card-title">Restaurant Inspections</div>
        <div class="card-status">Live</div>
      </div>
      <div class="card-tagline">DE Division of Public Health · Food establishment inspections</div>
      <div class="card-description">
        What state food inspectors recorded at restaurants and other food establishments, by establishment and date,
        in the state's own words. Search by name or town, or browse a town page. No grades or scores; a violation is not a closure.
      </div>
      <div class="card-meta-row">
        <span class="card-meta-pill">Office of Food Protection</span>
        <span class="card-meta-pill">55 towns</span>
        <span class="card-meta-pill">Weekly</span>
      </div>
      <span class="card-enter">Enter dashboard</span>
    </a>
```

Optional homepage JSON-LD `Dataset` entry, in the same list as the others:

```
{ "@type": "Dataset", "name": "Delaware restaurant inspection violations", "url": "https://firststatelens.com/inspections/", "description": "Food establishment inspection violations by establishment and date, in the state's own words. No grades or scores." },
```

## 5. .github/workflows/refresh-all.yml

Run line (in "Run all dashboard pullers", after Reassessment). The page step runs only if the pull succeeded:

```
          if python -m etl.sources.de_food_inspections --out inspections/data; then
            echo "OK: Inspections"
            python -m etl.pages.inspection_pages || { echo "FAILED: Inspection pages"; fail=1; }
          else
            echo "FAILED: Inspections"; fail=1
          fi
```

(The `run` helper only wraps `python -m`, so this pair uses an explicit `if`. The puller is keyless and takes about 16 s.)

Artifact path to add:

```
            inspections/
```

`git add` line: add `inspections sitemap.xml`. The generator writes the pages and `inspections/data/search-index.json` and rewrites the sitemap block.

```
          git add schools/data ... reassessment/data inspections sitemap.xml
```

## 6. .assetsignore

Nothing to add. `inspections/data/` must stay public: the search box fetches `/inspections/data/search-index.json`.

## Notes for integration

- Pages carry `<!-- generated by etl/pages/inspection_pages.py ... -->`. The generator deletes only pages that carry this marker and are no longer produced, such as a town that drops out of the file.
- A town page splits into alphabetical parts (`/inspections/<town>/<a-to-f>/`) when its establishment markup passes 900 KB. Today no town splits; Wilmington is 910 KB in total. When a split happens, the sitemap block picks up the new URLs automatically.
- Data size: `inspections/data/` is about 5.5 MB (55 town JSON files at indent 1, plus a 435 KB search index). Weekly diffs stay limited to the towns that changed.

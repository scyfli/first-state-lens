# Wiring: school-districts (Y3, school report card pages)

Branch `feat/school-districts`. Nothing below was applied to shared files; the lead wires it.

## sitemap.xml

Optional: also bump the existing `/schools/` line's lastmod to `2026-10-14` (its table now has static, linked rows).
Suggest wrapping these in `<!-- SCHOOLS:START -->` / `<!-- SCHOOLS:END -->` markers so a later run can regenerate them
(`python3 -m etl.pages.school_district_pages --print-sitemap` prints exactly these lines; lastmod = newest source portal update).

```xml
<!-- SCHOOLS:START (generated: python3 -m etl.pages.school_district_pages --print-sitemap) -->
  <url><loc>https://firststatelens.com/schools/district/academia-antonia-alonso/</loc><lastmod>2026-09-29</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/schools/district/academy-of-dover-charter-school/</loc><lastmod>2026-09-29</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/schools/district/appoquinimink/</loc><lastmod>2026-09-29</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/schools/district/aspira-delaware/</loc><lastmod>2026-09-29</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/schools/district/brandywine/</loc><lastmod>2026-09-29</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/schools/district/bryan-allen-stevenson-school-of-excellence/</loc><lastmod>2026-09-29</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/schools/district/caesar-rodney/</loc><lastmod>2026-09-29</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/schools/district/campus-community-school/</loc><lastmod>2026-09-29</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/schools/district/cape-henlopen/</loc><lastmod>2026-09-29</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/schools/district/capital/</loc><lastmod>2026-09-29</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/schools/district/charter-school-of-new-castle/</loc><lastmod>2026-09-29</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/schools/district/christina/</loc><lastmod>2026-09-29</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/schools/district/colonial/</loc><lastmod>2026-09-29</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/schools/district/delmar/</loc><lastmod>2026-09-29</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/schools/district/early-college-high-school-at-del-state/</loc><lastmod>2026-09-29</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/schools/district/east-side-charter-school/</loc><lastmod>2026-09-29</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/schools/district/edison-thomas-a-charter-school/</loc><lastmod>2026-09-29</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/schools/district/first-state-military-academy/</loc><lastmod>2026-09-29</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/schools/district/first-state-montessori-academy/</loc><lastmod>2026-09-29</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/schools/district/freire-charter-school-wilmington/</loc><lastmod>2026-09-29</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/schools/district/gateway-charter-school/</loc><lastmod>2026-09-29</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/schools/district/great-oaks-charter-school/</loc><lastmod>2026-09-29</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/schools/district/indian-river/</loc><lastmod>2026-09-29</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/schools/district/kuumba-academy-charter-school/</loc><lastmod>2026-09-29</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/schools/district/lake-forest/</loc><lastmod>2026-09-29</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/schools/district/laurel/</loc><lastmod>2026-09-29</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/schools/district/milford/</loc><lastmod>2026-09-29</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/schools/district/mot-charter-school/</loc><lastmod>2026-09-29</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/schools/district/new-castle-county-vocational-technical/</loc><lastmod>2026-09-29</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/schools/district/newark-charter-school/</loc><lastmod>2026-09-29</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/schools/district/odyssey-charter-school/</loc><lastmod>2026-09-29</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/schools/district/polytech/</loc><lastmod>2026-09-29</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/schools/district/positive-outcomes-charter-school/</loc><lastmod>2026-09-29</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/schools/district/providence-creek-academy-charter-school/</loc><lastmod>2026-09-29</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/schools/district/red-clay-consolidated/</loc><lastmod>2026-09-29</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/schools/district/seaford/</loc><lastmod>2026-09-29</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/schools/district/smyrna/</loc><lastmod>2026-09-29</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/schools/district/sussex-academy/</loc><lastmod>2026-09-29</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/schools/district/sussex-montessori-school/</loc><lastmod>2026-09-29</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/schools/district/sussex-technical/</loc><lastmod>2026-09-29</lastmod><priority>0.6</priority></url>
  <url><loc>https://firststatelens.com/schools/district/woodbridge/</loc><lastmod>2026-09-29</lastmod><priority>0.6</priority></url>
<!-- SCHOOLS:END -->
```

## llms.txt

Add under the existing School Report Card line:

```
- [School district report cards](https://firststatelens.com/schools/district/indian-river/): One page per Delaware LEA (41 school districts and charter schools, e.g. /schools/district/indian-river/): enrollment, Smarter Balanced proficiency, chronic absenteeism, graduation, classroom teacher average salary and salary ranges, each beside the statewide figure. Source: DE Department of Education via data.delaware.gov.
```

## scripts/a11y-audit.js ROUTES

One template, but add two routes so both table shapes are covered (a district with every measure, and a charter with the graduation note and missing values):

```
'/schools/district/indian-river/', '/schools/district/sussex-academy/'
```

## Homepage card

None. Not a new top-level dashboard; the pages hang off `/schools/`.

## .github/workflows/refresh-all.yml

In "Run all dashboard pullers", after `run "Schools" etl.sources.de_report_card`:

```
          run "Salary"    etl.sources.de_educator_salary
          run "SchoolPages" etl.pages.school_district_pages
```

(`run` calls `python -m "$@"`, which works for `etl.pages.*` too. The page generator must run after both pullers.
If either puller fails, the generator still runs on the last committed JSON, which is safe.)

Artifact path: already covered by `schools/data/`. Add `schools/district/` and `schools/index.html`:

```
            schools/district/
            schools/index.html
```

`git add` line: append `schools/district schools/index.html` (`schools/data` is already there and now also carries
`educator-salary.json` + `educator-salary-manifest.json`).

## .assetsignore

No change. `etl/` and `docs/` are already excluded. `schools/data/educator-salary*.json` are public data like the existing schools JSON.

## _headers, robots.txt, assets/fsl.css

No change. Page CSS is inline.

---
project: First State Lens — Civic Analytics Lab
task: Reframe FSL as a public civic-data utility and build an 8-dashboard citizen suite
slug: fsl-civic-suite
effort: E5
phase: verify
progress: 74/120
mode: build
started: 2026-06-15
updated: 2026-08-25
---

# First State Lens — Civic Analytics Lab (project ISA)

> **System of record for the civic-dashboard suite.** This ISA is the long-lived
> articulation of First State Lens's reframed mission: public, citizen-facing
> civic-data dashboards under the FirmSideAI Civic Analytics Lab. It grows as each
> dashboard is built. The DGI Food Access dashboard (the original build) keeps its
> own methodology record in the vault; this ISA governs the suite-level program and
> every new dashboard added under it.

## Problem

First State Lens was built as a civic-outcomes tool oriented toward government
workers and elected officials, anchored on one senator's legislative agenda, and
kept password-gated. That framing under-serves the actual mission. The data that
tells a citizen what their state and local government is prioritizing is public, but
it is scattered across dozens of portals, locked in PDFs, buried behind one-record-
at-a-time lookups, or rendered in formats no ordinary person can use. The result is
an information asymmetry: the already-resourced can afford analysts; everyone else
gets press releases. That asymmetry is the problem. (B3: AI as equalizer.)

## Vision

A citizen in Delaware opens First State Lens, types their address or picks their
district, and immediately understands something true about how their government is
spending, performing, and deciding — a fact they could not have assembled themselves,
rendered so plainly they instantly recognize it as true and trustworthy. Not advocacy.
Not a vendor's pitch. Just the public record, organized, sourced, and free. The brand
promise is "we show you the data, you decide." The euphoric surprise is that the
boring civic record, once organized, is genuinely empowering.

## Out of Scope

- **Advocacy or editorializing.** No dashboard tells the citizen what to conclude,
  who to vote for, or which policy is right. Value-laden framing is anti-vision.
- **Any data whose license prohibits redistribution.** Sussex County parcel data
  (GIS user agreement forbids copying/publishing/derivative works) is excluded until
  a county exception is granted. Lawful republication is a hard gate.
- **Private or re-identifying data.** Small-cell-suppressed cells stay suppressed;
  no attempt to back out individuals from aggregates.
- **National scope.** Delaware only ("First State"). Federal data is included only
  where it lands in or flows to Delaware.
- **Real-time / streaming.** Batch refresh on each source's natural cadence.
- **Going public before the suite is solid.** Public launch is a single gated event,
  not a default.

## Principles

- **Nonpartisan firewall as product.** Neutrality is not a posture; it is the moat.
  Every number cites its public source; every page states its method; no copy
  editorializes. This is what lets a commercial consultancy publish accountability
  data without being read as advocacy.
- **Probe values, not job status.** A source is "verified" only when a live probe
  returned real data, never when a job reported success. (Carries the silent-zero
  lesson: `orchestrator-must-thread-env-key`.)
- **Redistributable-or-excluded.** If the license forbids republication, the data
  does not ship, however useful. Lawfulness gates utility.
- **Additive, do-no-harm.** The restored DGI pipeline is touched additively only.
  New work on branches; DGI `data/` outputs unchanged after suite work.
- **Citizen-pull before accountability-push.** Lead with what people search for
  unprompted (schools, childcare); let the money-and-votes dashboards ride in behind
  the traffic.
- **Match what works.** New dashboards mirror the existing convention (sibling dir +
  static index.html + standalone puller in etl/sources/). No rebuild of working parts.

## Constraints

- **Stack:** Python ETL (`etl/sources/*.py` standalone-runnable modules + `etl/transforms/`
  + `etl/lib/` + datapackage writer), static `index.html` per dashboard, MapLibre for
  maps, Cloudflare Worker static-assets deploy (`wrangler.jsonc`), `.assetsignore`
  keeps etl/ and *.md private, `_headers` sets security + `X-Robots-Tag: noindex`.
  Project convention overrides the global TypeScript default.
- **Gating:** Site stays password-gated and `noindex` until an explicit public-launch
  flip. The flip is the one RED action requiring Mark's go (outward-facing,
  Google-indexing is not cleanly reversible).
- **DGI orchestrator (`run_etl.py`) is not modified destructively.** Each new dashboard
  gets its own thin ETL entrypoint writing to its own `<dashboard>/data/`.
- **Accessibility:** every dashboard passes the existing axe-core WCAG 2.2 AA CI gate.
- **Methodology versioning:** any tunable knob lives in `parameters.yaml`; changes bump
  the methodology version per repo discipline.
- **CENSUS_API_KEY** must be threaded into the orchestrated path of any Census-using
  puller (regression-tested), never only the `__main__` block.

## Goal

Reframe First State Lens into the FirmSideAI Civic Analytics Lab and ship a suite of
public, nonpartisan, source-cited citizen dashboards for Delaware. The suite is
"done enough to launch" when Wave 1 (Schools, Childcare, State Spending, Federal
Dollars, Water-violations) is built, source-cited, a11y-compliant, and deploy-verified
behind the gate, each carrying the neutrality-firewall header, with the build pipeline
proven repeatable for Waves 2 and 3.

## Criteria

### Suite-level (S)

- [ ] ISC-1: Anti: no dashboard renders a number without a visible cited public source (grep each index.html for a `.source` / citation block per stat group).
- [x] ISC-2: Every dashboard page renders the methodology + neutrality header. Verified: all 5 carry the "We show you the data; you decide." firewall line (grep gate).
- [x] ISC-3: Anti: no advocacy/editorializing copy. Verified: grep for (corrupt|shocking|alarming|outrageous|scandal|failing|disgrace|wasteful|reckless|shameful) across all 5 dashboards = 0 hits.
- [x] ISC-4: Each new dashboard is a sibling top-level dir with index.html matching the dgi-food-access layout (ls confirms). Verified 2026-08-25: `reassessment/` sibling dir + `reassessment/index.html` built on the shared `/assets/fsl.css` + topbar/title/neutrality/kpi-grid/section pattern; renders identically to the other 8 dashboards.
- [x] ISC-5: Each new ETL puller is a standalone-runnable module in etl/sources/ matching the census_acs.py pattern (Read confirms `--out` CLI + module docstring with Source/License/Cadence). Verified 2026-08-25: `etl/sources/kent_reassessment.py` has argparse `--out`, a module docstring with Source/License/Cadence, and a silent-zero guard; ran standalone → wrote real data.
- [ ] ISC-6: Anti: DGI data/ outputs are byte-unchanged after suite work (git diff dgi-food-access/data is empty unless a DGI-specific task touched it).
- [ ] ISC-7: Any new Census-using puller threads CENSUS_API_KEY through the orchestrated path, with a regression test asserting the key reaches the request (per silent-zero lesson).
- [x] ISC-8: Each dashboard passes scripts/a11y-audit.js (axe-core WCAG 2.2 AA), 0 violations. Verified 2026-06-22: CI run 27980626995 = PASS, all 9 routes 0 serious/critical. Fixed 6 color-contrast violations (1 rule/page): `.kpi-source` + `.footer-build` (slate-500@.9 → --text-tertiary) and unstyled in-table links (added accessible base `a` color). Commits 46d1fb8 + 0846928. a11y workflow paths widened to all dashboards.
- [x] ISC-9: All 5 dashboards carry `<meta robots noindex,nofollow>` (grep verified) and the client-side gate; `_headers` X-Robots-Tag noindex unchanged. Public flip remains Mark's RED checkpoint.
- [x] ISC-10: Anti: no redistribution-prohibited source ingested — Sussex parcel data never touched; the 4 friction sources (Sussex, NCC HTML, CFRS, lead address-level) all excluded or honestly-noted.
- [ ] ISC-11: This ISA's Features section names every dashboard's verified source + access method + GO/PARTIAL verdict.
- [ ] ISC-12: Each dashboard data payload carries a "data current as of" stamp and a source-age guard.

### Data-access verification (V) — DONE this turn, 8 live probes

- [x] ISC-13: Schools — data.delaware.gov Socrata GO, school+district SY15-25, no key (verified live, datasets ms6b-mt82 / crb4-kdc7 / t7e6-zcnn / 6i7v-xnmf resolve).
- [x] ISC-14: Childcare — FirstMap DE_ChildCareCenters FeatureServer GO, 1,547 features with capacity+STARS+geometry, no key + Census B09001 (verified live).
- [x] ISC-15: State Spending — data.delaware.gov 7bip-nb4g GO, 14.1M txn rows vendor-named, no key (verified live count).
- [x] ISC-16: Federal Dollars — api.usaspending.gov GO, keyless, place-of-performance=DE + recipient-state filters return real awards (verified live).
- [x] ISC-17: Water violations — EPA Envirofacts + ECHO GO, per-PWS DE violations keyless (verified live, 1,344 DE systems / 51 current violations).
- [x] ISC-18: Legislator Votes — Open States v3 + bulk + LegiScan GO, per-member roll-calls confirmed; needs free Open States key.
- [x] ISC-19: Federal campaign finance — FEC OpenFEC GO, individual contributions for DE; needs free api.data.gov key.
- [x] ISC-20: Reassessment — PARTIAL: Kent open API (real post-reassessment values), NCC geometry-only/values HTML, Sussex redistribution-PROHIBITED; state campaign finance PARTIAL (Telerik scrape); lead-lines PARTIAL (system-level only).

### Per-dashboard criteria (expand at each dashboard's build — Wave 1 detailed below)

**Schools (SC):**
- [x] ISC-21: etl/sources/de_report_card.py pulls 4 Socrata datasets, filters rowstatus='REPORTED', schoolcode='0' (state+district totals), Smarter Balanced only. Verified: state ELA 41.21% / Math 33.82% / grad 88.9% / chronic 17.13% / enroll 152,122; 41 LEAs. Caught + fixed a junk 'SchoolYear' literal that broke max-year on enrollment (numeric-year guard).
- [x] ISC-22: Anti: REDACTED rows are filtered out (numeric fields absent on them); missing values render as "—", never zero or text. Silent-zero guard raises if state ELA or <10 districts.
- [DEFERRED-VERIFY] ISC-23: per-pupil spending — Urban CCD finance returned 0 DE districts for 2021; deferred to v1.1 (try NCES F-33 / another year). Not a launch blocker (D13).
- [x] ISC-24: schools/index.html renders statewide KPIs + every-LEA table (enrollment, ELA, Math, chronic absenteeism, grad) with client-side sort; neutrality header explains Smarter Balanced, REPORTED-only, per-metric vintages, no good/bad coloring. Verified via HTTP serve.
- [x] ISC-25: each KPI + table cites its dataset id (ms6b-mt82/crb4-kdc7/t7e6-zcnn/6i7v-xnmf) + per-metric vintage (proficiency/chronic/enroll FY2025, grad FY2023).
- [x] ISC-26: schools/ route 200 — verified local HTTP serve; pushed to origin/main this turn → deploys to gated preview; a11y registered in ROUTES (CI).

**Childcare (CC):**
- [x] ISC-27: etl/sources/firstmap_childcare.py pulls DE_ChildCareCenters geojson, dedupes on RSR_RSRC_I (max capacity per resource). Verified: 1,198 distinct providers from 1,547 age-group rows, 66,850 capacity.
- [x] ISC-28: childcare access metric = capacity vs Census B09001 under-6, by COUNTY (FirstMap carries ADR_COUNTY → no geometry join needed; shapely absent). Verified: NCC 0.83 / Kent 1.33 / Sussex 1.40 children per slot. Tract-level desert map = v2.
- [x] ISC-29: childcare/index.html renders MapLibre provider map (1,198 points, capacity-sized, popups) + county access table + STARS bars + KPIs; neutrality header explains supply-vs-population (not waitlist) and STARS "Not Participating" caveat. Verified via HTTP serve.
- [x] ISC-30: Anti: per-age-group rows do not double-count capacity — deduped on RSR_RSRC_I (1,547→1,198). Census key threaded via os.environ (ISC-7 standalone-path satisfied; silent-zero guard raises on HTML-at-200).
- [x] ISC-31: childcare/ route 200 — verified local HTTP serve (page+summary+geojson 200, MapLibre wired); production deploy = git push; a11y registered in ROUTES, runs in CI.

**State Spending (SP):**
- [x] ISC-32: etl/sources/de_checkbook.py aggregates dataset 5s6n-7hpx (has `category`) by department/category/vendor via SoQL $group server-side (no row pull). Verified: FY2025 $16.9B / 1.55M txns.
- [x] ISC-33: amounts cast string→float in puller (_f helper); defaults to latest COMPLETE DE fiscal year (FY ends June 30) so a partial year is never headlined as complete.
- [x] ISC-34: spending/index.html renders dept + category bars + top-vendor table + KPIs, neutrality header (disbursements-not-budget + Medicaid pass-through caveat), per-block source tags, "data as of" stamp. Verified via HTTP serve.
- [x] ISC-35: spending/ route 200 — verified local HTTP serve (page+data 200, render targets present); production deploy = git push; a11y registered in ROUTES, runs in CI.

**Federal Dollars (FD):**
- [x] ISC-36: etl/sources/usaspending_de.py pulls DE place-of-performance awards (type counts + top-15 contracts + top-15 grants by amount), silent-zero guarded. Verified live: 17,988 FY2024 awards.
- [x] ISC-37: federal/index.html distinguishes "spent in DE" (place of performance) vs "to DE recipients" in the neutrality header; pass-through-grant caveat stated.
- [x] ISC-38: award-type breakdown bars + top-recipient tables (agency + recipient + amount) rendered from data/federal-summary.json, each block source-tagged. Verified via HTTP serve.
- [x] ISC-39: federal/ route 200 — verified over local HTTP serve (page+css+data all 200); production deploy is via git push + Mark's Chrome check (follow-up: push to scyfli/first-state-lens). a11y axe-core gate registered in scripts/a11y-audit.js ROUTES, runs in CI (puppeteer absent in WSL).

**Water (WA):**
- [x] ISC-40: etl/sources/epa_sdwa_de.py pulls DE violations via WATER_SYSTEM(STATE_CODE=DE)⋈VIOLATION on PWSID (the ONLY correct DE filter — `VIOLATION/STATE_CODE/DE` silently returns 3.4M national rows). ECHO avoided (429-throttled, unsuitable). Verified: 1,344 systems, 792 violations (434 health-based). Open/resolved via rtc_date (validated meaningful: national table has 2,776 no-rtc rows; DE genuinely has 0 open).
- [x] ISC-41: water/index.html — per-system table (violations / health-based / open / people served) sorted by severity, each linking to its EPA ECHO report; neutrality header explains "on record," health-based, open=no-rtc, quarterly sync. Verified via HTTP serve.
- [x] ISC-42: lead = honest system-level note only — Delaware publishes NO central address-level lead dataset; section links to the 3 per-utility inventories (New Castle MSC / Wilmington / Veolia). No fabricated counts.
- [x] ISC-43: water/ route 200 — verified local HTTP serve; pushed to origin/main → gated preview; a11y registered in ROUTES (CI).

### Wave 2 / Wave 3 (criteria expand at build)
- [x] ISC-44: Legislator Votes (Wave 2 #1) built on Open States v3 (free key). etl/sources/openstates_de.py aggregates the current session's recorded roll-call votes per legislator (member-votes are self-describing — voter.id/party/chamber/district/option — no roster join). Verified: session 153, 65 legislators (21 Senate / 41 House), 1,592 vote events / 925 bills; per-legislator yes/no/participation. votes/index.html = "find your legislator" filter + sortable table, NO party colors, no scoring (most-charged dashboard → strictest neutrality). Pushed. (Sponsorships/attendance detail = v1.1.)
- [x] ISC-45: Federal campaign finance built on FEC (OpenFEC via api.data.gov key). **VERIFIED 2026-07-23:** `etl/sources/fec_de.py` pulls `/candidates/totals?state=DE` for the cycle (name/office/party/receipts/disbursements/cash-on-hand), silent-zero guard (raises unless ≥1 candidate with filed receipts). Probed live: 19 DE 2026 candidates, 6 with filed receipts, $11.53M total raised (McBride $4.66M House, Coons $6.66M Senate). `campaign-finance/index.html` = raw as-filed numbers, party as a factual label (no color, no ranking, NO magnitude bars = strictest-neutrality posture matching Votes), FEC-registration≠ballot caveat. Neutrality grep 0 hits, render-verified. Homepage card + sitemap + a11y route + refresh-all wiring added. FEC_API_KEY set as repo secret.
- [x] ISC-46: Reassessment ships Kent-only, transparently labeled, NCC/Sussex flagged as access-pending. **VERIFIED 2026-08-25:** `etl/sources/kent_reassessment.py` (keyless) pulls AGGREGATE stats from Kent County's ArcGIS Parcels/FeatureServer/0 — countywide roll $29.42B across 83,004 parcels (80,925 valued), median $283,600, mean $363,595, land $9.14B / improvements $20.28B, 95 property-use classes, plus residential medians (Single Family $329,200 / Mobile Home $196,100 / Multi Family $290,600). `reassessment/index.html` renders median-led KPIs (mean disclosed in-context per advisor), residential-median table, and per-use table (top 20 + folded remainder). Neutrality header states Kent-only + NCC/Sussex access-pending. Rendered in real Chromium (localhost serve): all KPIs populated, 0 console errors, screenshot reviewed. Homepage card + JSON-LD dataset + sitemap + llms.txt + a11y route + refresh-all wiring all added.
- [x] ISC-47: Anti: Reassessment never publishes Sussex data without a written county exception. **VERIFIED:** the puller queries ONLY the Kent County ArcGIS endpoint; no Sussex source is touched. Page copy states "This dashboard covers Kent County only — New Castle and Sussex are not included here." grep of reassessment/index.html for "Sussex" = only the access-pending disclosure line.

## Test Strategy

| isc | type | check | threshold | tool |
|-----|------|-------|-----------|------|
| ISC-1 | grep | citation block per stat group | all present | Grep |
| ISC-3 | grep | value-laden term scan | 0 hits outside data labels | Grep |
| ISC-6 | git | DGI data/ diff | empty | Bash git diff |
| ISC-7 | test | key reaches request in orchestrated path | pass | bun/pytest |
| ISC-8 | a11y | axe-core WCAG 2.2 AA | 0 violations | scripts/a11y-audit.js |
| ISC-13..20 | live probe | source returns real data | resolved | WebFetch (done) |
| ISC-22/30 | test | suppression / dedupe handling | pass | pytest |
| ISC-26/31/35/39/43 | deploy | route 200 behind gate | 200 | curl |

## Features

| name | satisfies | source (verified) | access | verdict | depends_on | parallelizable |
|------|-----------|-------------------|--------|---------|------------|----------------|
| Schools | ISC-21..26 | data.delaware.gov Socrata + Urban/CCD | keyless REST | GO | suite scaffold | yes |
| Childcare | ISC-27..31 | FirstMap ArcGIS + Census B09001 | keyless + Census key | GO | sb254/apportion transforms | yes |
| State Spending | ISC-32..35 | data.delaware.gov 7bip-nb4g | keyless Socrata | GO | suite scaffold | yes |
| Federal Dollars | ISC-36..39 | api.usaspending.gov | keyless | GO | suite scaffold | yes |
| Water | ISC-40..43 | EPA Envirofacts + ECHO | keyless | GO | suite scaffold | yes |
| Legislator Votes | ISC-44 | Open States v3 + LegiScan | free key | GO | Open States key | yes |
| Federal campaign $ | ISC-45 | FEC OpenFEC | free key | GO | FEC key | yes |
| Reassessment (Kent) | ISC-46,47 | Kent County ArcGIS (gis.kentcountyde.gov Parcels/FeatureServer/0) | keyless | GO | none | yes |
| State campaign $ | — | DE CFRS | Telerik scrape | PARTIAL (deferred) | scraper | no |
| Lead lines layer | ISC-42 | per-utility ArcGIS | scrape | PARTIAL (folded into Water) | Water | no |

## Decisions

- 2026-06-15 D1: Reframed FSL from gov/electeds tool to public civic-data utility under
  the FirmSideAI Civic Analytics Lab. Mark's call; B3 mission lane.
- 2026-06-15 D2: Keep it FirmSideAI-branded; do NOT route through Luna; do NOT form a
  new nonprofit yet (prove first, fiscal sponsorship before incorporation). Distribution
  via nonpartisan civic orgs (League of Women Voters DE, libraries, Delaware Public
  Media, UDel Biden School/DSI, Spur Impact) is the leverage, not ownership.
- 2026-06-15 D3: Stack stays Python ETL + static Cloudflare; project convention overrides
  global TS default. Adding TS rewrites mid-stream = change-stacking (C2/M4), rejected.
- 2026-06-15 D4: Neutrality firewall = per-page methodology+source header + per-number
  citation + no editorializing. This IS the brand.
- 2026-06-15 D5: Public-launch flip is the single RED checkpoint Mark holds; everything
  up to it is autonomous. Build proceeds gated + noindex.
- 2026-06-15 D6 (refined): Build order revised after data verification. Reassessment
  removed as opener — Sussex GIS user agreement legally prohibits redistribution and NCC
  hides values behind HTML. New opener: Schools + Childcare (cleanest GO; Childcare reuses
  food-desert methodology). Reassessment rescoped to Kent-only.
- 2026-06-15 D7: Two free API keys needed for Wave 2 (Open States, FEC api.data.gov);
  batched to Mark rather than asked one at a time.
- 2026-06-15 D8 (show-your-math, delegation floor): E5 delegation floor is 4; this OBSERVE
  turn used 8 parallel verification agents (exceeds floor). Build delegation (Forge per
  dashboard puller) fires at each Wave-1 dashboard build, not this turn.
- 2026-06-15 D9: Shared design system extracted to assets/fsl.css (tokens + components +
  gate styles) so the suite reads as one product; DGI keeps its inline styles (do-no-harm).
  New dashboards link it; per-dashboard accent overrides --accent-primary.
- 2026-06-15 D10: Suite-shared client-side gate — same password HASH as DGI, STORAGE_KEY
  "fsl-gate-2026-06" so unlocking one new dashboard unlocks the others in-session. a11y +
  visual verification is the CI axe-core gate + Mark's Chrome check (puppeteer/Interceptor
  absent in WSL — the project's standing constraint), not a local browser this turn.
- 2026-06-15 D11 (scope honesty): Wave 1 ships dashboard-by-dashboard, each fully built +
  live-data-verified before the next. Federal Dollars shipped + verified this turn as the
  template; Spending/Water/Schools clone the pure-API pattern; Childcare waits on the
  Census key. One verified dashboard beats five stubs (the Incomplete-Work failure class).
- 2026-06-15 D12 (Water groundwork, probed live this turn — built next):
  ECHO is rate-limited (300/hr; we hit the throttle during probing) → confirms the data
  MUST be pre-baked by ETL, never client-fetched. Backbone = EPA Envirofacts efservice
  (keyless, no aggressive limit). Confirmed live: `data.epa.gov/efservice/WATER_SYSTEM/
  STATE_CODE/DE/COUNT/JSON` = 1,344 systems; `.../VIOLATION/STATE_CODE/DE/.../JSON` returns
  rows with `pwsid, pws_name(via WATER_SYSTEM join), pws_type_code, violation_code,
  violation_category_code (MCL/...), is_health_based_ind (Y/N), contaminant_code,
  compliance_status_code (R=returned-to-compliance vs open), viol_measure, unit_of_measure`.
  OPEN before build (the accuracy gate): (1) confirm compliance_status_code value set so
  "current/open" vs "resolved" is labeled correctly — do NOT call resolved violations
  "current" on a health page; (2) get VIOLATION COUNT for DE to avoid silent truncation
  (show "N of M"); (3) join VIOLATION→WATER_SYSTEM on pwsid for system names; (4) lead-line
  layer = system-level only, link out to per-utility ArcGIS maps. Build Water as a careful
  next step, not a rushed clone.
- 2026-06-15 D13 (Schools groundwork, probed live this turn — built next):
  data.delaware.gov Socrata, keyless: assessment `ms6b-mt82` (max year 2025), attendance
  `crb4-kdc7` (2025), graduation `t7e6-zcnn` (max year 2023 — lags two years; label each
  metric's vintage, never imply same year). Accuracy gates: (1) numeric fields
  (`pctproficient` etc.) are ABSENT on `rowstatus='REDACTED'` rows — MUST filter
  `rowstatus='REPORTED'` or the pipeline ingests nulls (silent-corrupt); (2) `geography` is
  NOT a level indicator (always 'All Students'); `subgroup='All Students'` gives the
  all-students total but BOTH school and district rows carry it, so isolate district totals
  via the schoolcode/organization pattern before building (probe `district==organization`
  or a district-total schoolcode); (3) per-pupil: Urban CCD finance returned 0 DE districts
  for 2021 — try another year or NCES F-33; per-pupil is a v1.1 add, not a launch blocker.
- 2026-06-15 D14 (keys received): Mark provided Census (used — Childcare live), Plural/Open
  States, and data.gov/FEC keys via a Desktop file. Census threaded into the childcare
  puller. Plural + FEC are Wave 2 (Votes, federal campaign finance). The keys file is on the
  Desktop — reminded Mark to delete it once Wave 1 verifies. No key is committed to git.
- 2026-06-15 D15 (pre-index visual readability pass — Mark's gate before indexing):
  Every chart bar now COLOR-ENCODES, never decorates: Federal award-type bars = distinct
  categorical hues (nominal); Spending dept/category bars = harmonious palette cycled by
  rank so adjacent bars differ; Childcare STARS = ordinal gold ramp (deeper gold = more
  stars), grey for "Not Participating" (never red — not a low rating). KPI cards gained a
  themed top-accent stripe. Schools (41 LEAs) + Water (165 systems) dense tables gained
  neutral in-cell magnitude bars (percentages on a true 0–100 scale; counts to column max)
  for scannability. Discipline held: color is ALWAYS supplementary (every bar/cell keeps
  its label + value, WCAG 1.4.1) and never encodes good/bad (neutrality firewall intact).
  CSS/JS-only; verified via node --check + HTTP serve; commit 4e890ea. Final visual
  confirmation is Mark's Chrome pass (Interceptor absent in WSL).
- 2026-06-15 D16 (Wave 2 started — Votes shipped): Open States DE coverage validated before
  building (recent unvoted bills show 0 votes, but 925/1,239 session-153 bills DO carry
  per-member votes — coverage is real). Built on Open States v3 (key from the keys file).
  **CI wiring owed:** OPENSTATES_API_KEY (and FEC_API_KEY for the next dashboard) must be
  added as repo secrets + the ETL workflow extended to run these pullers, the same way
  CENSUS_API_KEY is wired — until then the votes data is the committed static snapshot.
  Next Wave-2 dashboard: Federal campaign finance (FEC, key in hand).
- 2026-06-16 D17 (three production fixes after Mark couldn't see the colors — a hard,
  multi-failure debugging arc):
  (a) **Cache:** `_headers` set no `Cache-Control`; Cloudflare/browser cached gated pages
  (cf-cache-status HIT). Added `Cache-Control: no-cache` so deploys aren't masked. (commit a1093ff)
  (b) **Homepage nav:** all 6 new dashboards were ORPHAN routes — the homepage grid only
  linked the original Clean Slate + DGI cards, so visitors landing on firststatelens.com
  never reached them. Added 6 cards + broadened the hero to the data-for-the-people mission. (143bb41)
  (c) **THE REAL BUG — bar charts had no color:** `.bar-fill` was an inline `<span>` with no
  `display:block`. Inline elements IGNORE width/height, so every colored fill had the right
  background on a zero-size box — only the faint grey track painted. getComputedStyle reported
  `width:100%` (unresolved %), which was the tell I misread as success. Fix: `display:block`
  (+ taller 30px bolder bars). Confirmed via headless render: bar now 403x28px painting
  rgb(251,191,36). Fixes federal/spending/childcare bar charts. (commit a2ef409, LIVE-verified
  in production CSS.) Lesson: getComputedStyle reports the STYLE, not whether it's laid out/painted
  — a raw `%` width back from getComputedStyle means the element isn't being laid out.
  **CONFIRMED by Mark 2026-06-16** — a fresh/separate browser shows the bar colors clean; his
  original browser had cached the pre-fix CSS (the no-cache header now prevents recurrence). Color bug CLOSED.
- 2026-06-22 D18 (PUBLIC LAUNCH — the RED flip, Mark's explicit go): flipped 6 dashboards
  + homepage to public + indexable; held DGI Food Access + Clean Slate. Removed the
  noindex meta + client-side password gate from federal/spending/childcare/schools/water/
  votes; scoped `_headers` X-Robots-Tag noindex to ONLY /dgi-food-access/* + /clean-slate/*;
  added robots.txt (disallow the 2 held dirs) + sitemap.xml (home + 6). Homepage: removed
  noindex, pulled the 2 held cards, replaced soft-launch/"not for public distribution" copy.
  Commit 2e5b464. LIVE-VERIFIED 2026-06-22: home/water/votes → 200 + no X-Robots-Tag
  (indexable); dgi/clean-slate → 200 + noindex (held); robots.txt + sitemap.xml → 200;
  water renders ungated with neutrality header; a11y CI green on 2e5b464. ISC-26/31/35/39/43
  now live + public (flipped to [x]). Supersedes ISC-9's "flip remains pending" status.
- 2026-06-22 D19 (content-alignment audit before the flip — Mark's requirement): 9 parallel
  page reviews against the neutrality rubric. The 6 post-pivot dashboards PASSED (sourced,
  no editorializing, honest caveats, the high-risk semantics — water open/resolved, federal
  place-of-performance, spending disbursement-vs-budget, childcare supply-vs-waitlist, votes
  no-scoring — all handled). The 2 ORIGINAL dashboards (DGI, Clean Slate) FAILED: they still
  carry electeds-accountability advocacy framing (DGI "tests DSB's claim" + a sponsoring
  senator's quote + placeholder county data rendered as real; Clean Slate "Promise vs.
  Reality" + governor's "reprehensible" quote + a 47-yr alarm-red projection), have no
  neutrality header, and are tagged scaffold/build-0.1.0. Decision: launch the 6, HOLD the 2
  for a de-advocacy rebuild (Mark's call). Small fixes applied to the 6 in the same pass:
  footer source-claim accuracy, childcare map caption (colored→sized), schools chronic
  value-judgment line removed.

## Changelog

- conjectured: all 8 proposed dashboards have clean redistributable public data.
  refuted_by: live probe of Sussex County GIS user agreement (prohibits copy/publish/
  derivative works) + NCC values being HTML-only + DE CFRS having no export/API.
  learned: "public data" is not "redistributable, machine-accessible data" — license and
  access method must each be probed, not assumed; the official source is often NOT the
  machine-accessible one (votes, campaign finance live in aggregators).
  criterion_now: ISC-10 (no redistribution-prohibited source) + ISC-20 (friction recorded)
  + D6 (build order revised around lawful access).
- conjectured: EPA's `VIOLATION/STATE_CODE/DE` Envirofacts endpoint returns Delaware
  drinking-water violations.
  refuted_by: live probe — it returned 3,425,122 rows with a Region-1 (New England) sample
  (pwsid prefix 01); the VIOLATION table has no usable state column, so the "DE" filter
  silently no-ops and would have ingested national data labeled Delaware.
  learned: filter water violations by JOINING through WATER_SYSTEM (which DOES filter on
  STATE_CODE=DE) on PWSID; and validate open/resolved semantics via rtc_date presence,
  confirmed meaningful by checking the national table has 2,776 no-rtc rows before trusting
  Delaware's genuine 0-open. Probe values, not endpoint existence.
  criterion_now: ISC-40 (join-based DE filter) + D12.
- conjectured: all 8 dashboards are ready to go public together once the gate comes off.
  refuted_by: a 9-page content-alignment audit before the flip — the 6 post-pivot dashboards
  hold the neutrality firewall, but the 2 oldest (DGI Food Access, Clean Slate) still read as
  advocacy instruments (sponsoring-senator + governor quotes, "Promise vs. Reality" / "tests
  the claim" framing, a 47-year alarm-red projection, and placeholder data rendered as real),
  with no neutrality header. They predate the civic-utility pivot and never got rewritten.
  learned: a suite-wide methodology pivot does not retroactively clean the pages built under
  the old model; the oldest artifacts carry the previous mission's DNA and must be re-audited
  page-by-page before a public launch — the neutrality brand is only as strong as the weakest
  page. The fix is to launch the clean pages and hold the legacy ones, not to flip everything.
  criterion_now: D18 (launch 6, hold 2) + D19 (content audit) + a future rebuild ISC for the
  2 held pages before they rejoin the public suite.

## Verification

- ISC-13..20: 8 parallel general-purpose agents, each fetched live endpoints and returned
  GO/PARTIAL with quoted real data (DE system counts, dataset row counts, sample records,
  field lists). Evidence captured in session transcript 2026-06-15. Five clean GO, two
  free-key GO, three friction cases recorded with the specific constraint named.
- ISC-36..38 (Federal Dollars): `python3 -m etl.sources.usaspending_de` returned 17,988
  FY2024 DE awards (contracts 10,926 / grants 2,821 / direct 2,604 / loans 892 / other 745),
  top contract Caesar Rodney School District $53.3M (DoD), top grant DE DHSS $2.4B. Page +
  /assets/fsl.css + data/federal-summary.json all HTTP 200 over local serve; all render-target
  IDs + gate + noindex present in served HTML. ISC-39 deferred to production push + CI a11y.

## 2026-08-25 — Reassessment (Kent) dashboard — the 8th and FINAL suite dashboard (Mark: "catch up on the site build in completion")

**Conjecture → refutation → learning → criterion-now:**
- *Conjecture:* ISC-20 recorded "Kent open API (real post-reassessment values)" but never captured the endpoint. *Refutation/recovery:* rediscovered it — `https://gis.kentcountyde.gov/server/rest/services/Parcels/Parcels/FeatureServer/0` (keyless, open ArcGIS Server; the AGOL org root 400s, the on-prem server directory is the live path). *Learning:* record the exact endpoint in the puller docstring so ISC-20-style "verified live" claims stay reproducible. *Criterion-now:* ISC-46 evidence names the endpoint.
- *Conjecture (design):* lead the dashboard with the countywide average ($363,595). *Refutation:* the Advisor pass flagged mean-on-right-skew as misleading and "revenue-neutral" reassurance as itself a form of advocacy. *Learning:* for assessment data the neutral default is **median-led + segmented by property use + no tax figure + no before/after** (the basis change would manufacture a false spike). *Criterion-now:* the page leads with median ($283,600), discloses the mean in-context, segments by use, computes no tax, shows no old-vs-new — recorded as D-reassess-1.

**What shipped (all verified this session):**
- `etl/sources/kent_reassessment.py` — keyless AGGREGATE-only puller (never reads owner PII), silent-zero guards (parcels < 50k or roll < $1B → raise). Ran standalone → $29.42B roll, 83,004 parcels, median $283,600, mean $363,595, 95 use classes, residential medians. Writes `reassessment/data/{kent-reassessment-summary,manifest}.json`.
- `reassessment/index.html` — median-led KPIs, residential-median table, per-use table (top-20 + folded remainder), neutrality header (not-a-tax-bill + rate rollback 36¢→5.72¢ as a plain sourced fact + Kent-only + aggregates-only). Dataset JSON-LD.
- Wire-ins: homepage card (accent #c99a6b) + homepage JSON-LD dataset entry + sitemap.xml + llms.txt + a11y ROUTES + refresh-all.yml (run line + artifact path + git-add path).

**Verification (rungs reached):**
- Puller: actual stdout captured + JSON read back from disk (real values, not zeros).
- Page + data + homepage: HTTP 200 over local serve; JSON shape confirmed.
- Render (real Chromium via Playwright — Interceptor absent on this WSL box, same as prior FSL sessions): all KPIs populated (median $283,600 / SFD $329,200 / total $29.4B / split $9.1B–$20.3B), residential 3 rows + use 21 rows, correct data-as-of stamp, **0 console errors**, full-page screenshot reviewed. Homepage: reassessment card renders, 11 cards total, 0 console errors.
- Neutrality grep (advocacy lexicon incl. burden/spike/unfair) = 0 hits. Tax-leak grep = disclaimers + mechanism only, no computed tax.
- a11y: page reuses the axe-passing template (2 captions, 7 `scope=col`, `<main>`, 3 aria-label/ledby); the puppeteer axe run happens in CI post-push (puppeteer absent locally — rung named, not asserted).

## 2026-07-23 — Data-refresh audit + keyless refresh (resume, Mark: "update all dashboards end to end")

**Root cause found:** all 6 main dashboards were frozen at the 2026-06-15 build. The ONLY ETL
workflows are `bill-tracker-etl` (openstates_bill, daily) and `dgi-etl` (run_etl, monthly) —
**no workflow refreshes schools/childcare/spending/federal/water/votes.** Their pullers never
re-ran. This is the durability gap.

**End-to-end data-source audit (live-probed this session):**
| Dashboard | Source | Key | Status 2026-07-23 |
|---|---|---|---|
| Federal | api.usaspending.gov | none | ✅ refreshed FY2024→**FY2025** (12,678 awards), render-verified |
| Spending | data.delaware.gov checkbook | none | ✅ refreshed FY2025→**FY2026** ($17.03B/1.54M), render-verified |
| Water | EPA Envirofacts | none | ✅ re-verified live (1,344 sys / 792 viol / 0 open) |
| Schools | data.delaware.gov Socrata | none | ✅ source live; SY2025 still latest DE published (unchanged) |
| Childcare | FirstMap + Census B09001 | CENSUS_API_KEY | ⏳ stale June-15; refresh via CI (secret EXISTS) |
| Votes | Open States v3 | OPENSTATES_API_KEY | ⏳ stale June-15; refresh via CI (secret EXISTS) |
| DGI Food Access | SB254 + MMG | none/Census | ⚠️ MMG county join incomplete; KPIs hardcoded |
| Candidates | manual | none | ✅ current (7/14) |
| Clean Slate | — | — | ❌ HELD: no machine-readable DELJIS/SBI dataset (FOIA-gated) |
| FEC finance | FEC OpenFEC | data.gov key | ❌ unbuilt; key MISSING (no secret, keys file deleted) |
| Reassessment-Kent | Kent ArcGIS | none | ❌ unbuilt (keyless, buildable) |

**Shipped:** keyless refresh committed `d6145a4`, pushed → Cloudflare deploying. Render-verified
Federal (FY2025) + Spending (FY2026) display new data cleanly (charts+tables, silent-zero guards passed).

**Key insight:** `CENSUS_API_KEY` + `OPENSTATES_API_KEY` already exist as GitHub secrets. So a
`refresh-all` CI workflow can refresh Childcare + Votes without Mark re-providing keys. Only the
FEC/data.gov key is genuinely missing.

**Next slices:** (1) build `refresh-all.yml` CI workflow (cron, runs all pullers w/ existing secrets,
commits) — the durability fix + refreshes Childcare/Votes end-to-end; (2) FEC dashboard (ISC-45) —
needs Mark to add the data.gov key as a repo secret; (3) DGI MMG county join finish; (4) Reassessment-Kent
(ISC-46, keyless); (5) Clean Slate stays HELD unless a real DELJIS/SBI source surfaces (research, likely FOIA).

**DONE 2026-07-23 (this session):** (1) **`refresh-all.yml` built + ran** (run 30053107655 success, commit `0aecb85`) — Childcare + Votes + the keyless four all refreshed via CI using the existing CENSUS/OPENSTATES secrets; weekly cron now keeps them fresh. Keyless four also refreshed directly + deployed (`d6145a4`). (2) **FEC dashboard (ISC-45) built + verified + wired public** — Mark provided the api.data.gov key (set as `FEC_API_KEY` secret). (3) **Clean Slate = HELD confirmed** (Mark's call). (4) **data.gov repo clarified**: `GSA/data.gov` is the catalog *website* source (no datasets); the real lever is a free api.data.gov key (unlocks FEC + niche federal APIs), which is now in hand. **STILL OPEN:** DGI MMG county join finish; Reassessment-Kent (ISC-46, keyless, unbuilt). **Neighbor flagged:** the Candidates dashboard states "US Senate NOT up in 2026," but FEC shows a live 2026 DE Senate race (Coons, $6.66M) — reconcile before that claim misleads.

## 2026-07-23 — Full SEO/AEO pass (Mark: "fix the AEO and SEO... maximum visibility... everyone who needs this site must be able to find it, test it end to end")

**Changelog (conjecture/refutation):**
- conjectured: the public site was already discoverable — it went LIVE + public, so search engines can find it.
  refuted_by: a live head-audit — the flagship `index.html` carried near-zero metadata (no description, canonical, Open Graph, Twitter, JSON-LD, or favicon), no dashboard had `Dataset` structured data (invisible to Google Dataset Search), `/llms.txt` 404'd, and — worst — `/candidates/*` served `X-Robots-Tag: noindex, nofollow` at the edge while simultaneously listed in sitemap.xml and allowed in robots.txt (invited then blocked).
  learned: "public + in the sitemap" is not "indexable." Indexability is a conjunction across four independent surfaces (robots.txt, sitemap, per-page robots meta, edge X-Robots-Tag header); a stale header on ONE silently defeats the other three. A half-finished flip (robots + sitemap done, header missed) is worse than a clean hold, because it wastes crawl budget on pages it then blocks. Audit the served headers, not just the HTML.
  criterion_now: ISC-48..ISC-56.
- reconciled: the neighbor-flagged "US Senate NOT up in 2026" error is NOT present in current HTML — both `/candidates/` and `/campaign-finance/` correctly state a 2026 U.S. Senate seat (Coons, Class 2) is up. Fixed in a prior session; the ISA note was stale. Verified by full-repo grep (zero "not up"/"no Senate" claims).

### SEO/AEO criteria (2026-07-23)

- [x] ISC-48: Homepage carries full SEO head — description, canonical, robots(index,follow), Open Graph, Twitter card, favicon, theme-color. Verified: live curl of `https://firststatelens.com/` returns all tags.
- [x] ISC-49: Homepage carries valid Organization + WebSite + DataCatalog JSON-LD enumerating all 10 dashboards. Verified: validator.schema.org (Google) detected DataCatalog + WebSite, **0 errors**.
- [x] ISC-50: Every public dashboard (10) has canonical + OG + Twitter + `Dataset` JSON-LD with sourceOrganization + spatialCoverage(Delaware) + isAccessibleForFree. Verified: /tmp validator PASS 13/13 non-held pages (canon=1, jsonld parses); Google validator on schools + water = Dataset, **0 errors**.
- [x] ISC-51: `/candidates/*` un-blocked — stale noindex X-Robots-Tag removed. Verified: live `curl -I /candidates/` and `/candidates/us-house/` return NO x-robots-tag; `/clean-slate/` control still `noindex` (intentional hold).
- [x] ISC-52: `/llms.txt` exists for AI answer engines (was 404). Verified: live HTTP 200, describes org + every dashboard with source.
- [x] ISC-53: robots.txt names explicit AI-crawler allows (GPTBot, OAI-SearchBot, ClaudeBot, PerplexityBot, Google-Extended, Applebot-Extended, etc.). Verified: live robots.txt grep.
- [x] ISC-54: sitemap.xml lastmod reflects the real 2026-07-23 state (was frozen at 2026-06-22). Verified: live sitemap has 13 URLs at 2026-07-23.
- [x] ISC-55: Brand assets exist + serve — favicon.svg, apple-touch-icon.png (180×180), assets/og-image.png (1200×630). Verified: live 200 + correct content-type; og-image viewed (on-brand render).
- [x] ISC-56: Anti: internal work-record files (ISA.md, SESSION-HANDOFF.md) are NOT served publicly. Verified: added to .assetsignore (were previously reachable at /ISA.md).
- [x] ISC-9 (evolved): the "dashboards carry noindex + gate; public flip is Mark's RED checkpoint" condition is retired — Mark approved the flip 2026-07-23; dashboards are public and indexable. clean-slate remains the sole held page.

**Cross-vendor second look:** Forge (GPT-5.4) fanned out + self-validated the 8 dashboard head blocks (8/8 JSON-LD parse, single-canonical, additions-only); Google's validator independently confirmed 0 schema errors. Rule 2a floor satisfied without a Decisions skip-row.

**Deploy:** commit `20472f5` pushed to main → Cloudflare Pages deployed (~32s), all live-verified.

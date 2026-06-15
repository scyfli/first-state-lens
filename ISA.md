---
project: First State Lens — Civic Analytics Lab
task: Reframe FSL as a public civic-data utility and build an 8-dashboard citizen suite
slug: fsl-civic-suite
effort: E5
phase: build
progress: 38/120
mode: build
started: 2026-06-15
updated: 2026-06-15
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
- [ ] ISC-2: Every dashboard page renders the one-paragraph methodology + neutrality statement header (Read each index.html, confirm present).
- [ ] ISC-3: Anti: no advocacy/editorializing copy in any dashboard (grep gate for value-laden terms: "should", "must", "corrupt", "failing", "best/worst" outside data labels).
- [ ] ISC-4: Each new dashboard is a sibling top-level dir with index.html matching the dgi-food-access layout (ls confirms).
- [ ] ISC-5: Each new ETL puller is a standalone-runnable module in etl/sources/ matching the census_acs.py pattern (Read confirms `--out` CLI + module docstring with Source/License/Cadence).
- [ ] ISC-6: Anti: DGI data/ outputs are byte-unchanged after suite work (git diff dgi-food-access/data is empty unless a DGI-specific task touched it).
- [ ] ISC-7: Any new Census-using puller threads CENSUS_API_KEY through the orchestrated path, with a regression test asserting the key reaches the request (per silent-zero lesson).
- [ ] ISC-8: Each dashboard passes scripts/a11y-audit.js (axe-core WCAG 2.2 AA), 0 violations.
- [ ] ISC-9: Site remains noindex + gated until launch (Read _headers confirms `X-Robots-Tag: noindex`).
- [ ] ISC-10: Anti: no redistribution-prohibited source is ingested (Sussex parcel data absent from any committed data/).
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
- [ ] ISC-21: etl/sources/de_report_card.py pulls Socrata datasets, filters rowstatus='REPORTED', returns real rows.
- [ ] ISC-22: Anti: no `REDACTED`/`NOT REPORTED` string is ever rendered or cast as a numeric value.
- [ ] ISC-23: Urban/CCD finance puller adds district per-pupil (exp_total / enrollment).
- [ ] ISC-24: schools/index.html renders school + district selector with proficiency, grad rate, chronic absenteeism, enrollment, per-pupil.
- [ ] ISC-25: every metric block cites its dataset id + vintage.
- [ ] ISC-26: deploy-verify schools/ route returns 200 behind the gate.

**Childcare (CC):**
- [x] ISC-27: etl/sources/firstmap_childcare.py pulls DE_ChildCareCenters geojson, dedupes on RSR_RSRC_I (max capacity per resource). Verified: 1,198 distinct providers from 1,547 age-group rows, 66,850 capacity.
- [x] ISC-28: childcare access metric = capacity vs Census B09001 under-6, by COUNTY (FirstMap carries ADR_COUNTY → no geometry join needed; shapely absent). Verified: NCC 0.83 / Kent 1.33 / Sussex 1.40 children per slot. Tract-level desert map = v2.
- [x] ISC-29: childcare/index.html renders MapLibre provider map (1,198 points, capacity-sized, popups) + county access table + STARS bars + KPIs; neutrality header explains supply-vs-population (not waitlist) and STARS "Not Participating" caveat. Verified via HTTP serve.
- [x] ISC-30: Anti: per-age-group rows do not double-count capacity — deduped on RSR_RSRC_I (1,547→1,198). Census key threaded via os.environ (ISC-7 standalone-path satisfied; silent-zero guard raises on HTML-at-200).
- [DEFERRED-VERIFY] ISC-31: childcare/ route 200 — verified local HTTP serve (page+summary+geojson 200, MapLibre wired); production deploy = git push; a11y registered in ROUTES, runs in CI.

**State Spending (SP):**
- [x] ISC-32: etl/sources/de_checkbook.py aggregates dataset 5s6n-7hpx (has `category`) by department/category/vendor via SoQL $group server-side (no row pull). Verified: FY2025 $16.9B / 1.55M txns.
- [x] ISC-33: amounts cast string→float in puller (_f helper); defaults to latest COMPLETE DE fiscal year (FY ends June 30) so a partial year is never headlined as complete.
- [x] ISC-34: spending/index.html renders dept + category bars + top-vendor table + KPIs, neutrality header (disbursements-not-budget + Medicaid pass-through caveat), per-block source tags, "data as of" stamp. Verified via HTTP serve.
- [DEFERRED-VERIFY] ISC-35: spending/ route 200 — verified local HTTP serve (page+data 200, render targets present); production deploy = git push; a11y registered in ROUTES, runs in CI.

**Federal Dollars (FD):**
- [x] ISC-36: etl/sources/usaspending_de.py pulls DE place-of-performance awards (type counts + top-15 contracts + top-15 grants by amount), silent-zero guarded. Verified live: 17,988 FY2024 awards.
- [x] ISC-37: federal/index.html distinguishes "spent in DE" (place of performance) vs "to DE recipients" in the neutrality header; pass-through-grant caveat stated.
- [x] ISC-38: award-type breakdown bars + top-recipient tables (agency + recipient + amount) rendered from data/federal-summary.json, each block source-tagged. Verified via HTTP serve.
- [DEFERRED-VERIFY] ISC-39: federal/ route 200 — verified over local HTTP serve (page+css+data all 200); production deploy is via git push + Mark's Chrome check (follow-up: push to scyfli/first-state-lens). a11y axe-core gate registered in scripts/a11y-audit.js ROUTES, runs in CI (puppeteer absent in WSL).

**Water (WA):**
- [ ] ISC-40: etl/sources/epa_sdwa_de.py pulls per-PWS DE violations from Envirofacts, server-side cached (ECHO rate-limit respected).
- [ ] ISC-41: water/index.html lets a citizen find their water system + violations, health-based flagged.
- [ ] ISC-42: lead layer shows system-level "reports N lead / N unknown" only, explicitly NOT an address-level claim.
- [ ] ISC-43: deploy-verify water/ route 200 behind gate.

### Wave 2 / Wave 3 (criteria expand at build)
- [ ] ISC-44: Legislator Votes built on Open States (free key) + LegiScan fallback, per-member votes, sponsors, attendance.
- [ ] ISC-45: Federal campaign finance built on FEC (free key), DE candidate committees.
- [ ] ISC-46: Reassessment ships Kent-only, transparently labeled, NCC/Sussex flagged as access-pending.
- [ ] ISC-47: Anti: Reassessment never publishes Sussex data without a written county exception.

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
| Reassessment (Kent) | ISC-46,47 | Kent County ArcGIS | keyless | PARTIAL | none | yes |
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

## Changelog

- conjectured: all 8 proposed dashboards have clean redistributable public data.
  refuted_by: live probe of Sussex County GIS user agreement (prohibits copy/publish/
  derivative works) + NCC values being HTML-only + DE CFRS having no export/API.
  learned: "public data" is not "redistributable, machine-accessible data" — license and
  access method must each be probed, not assumed; the official source is often NOT the
  machine-accessible one (votes, campaign finance live in aggregators).
  criterion_now: ISC-10 (no redistribution-prohibited source) + ISC-20 (friction recorded)
  + D6 (build order revised around lawful access).

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

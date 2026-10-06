# First State Lens: Fall 2026 Upgrade Plan and Builder Instructions

Version 1.0 · 2026-10-05 · Approved scope: all items in Part A (Mark, 2026-10-05: "All pages approved after election pages built").
Owner: Mark Sanders (FirmSideAI). Builder: an AI coding agent (Claude Code / Trazyn, or a delegated agent such as Forge).

This document has two parts:
- **Part A: Scope.** What gets built, in what order, with what acceptance criteria.
- **Part B: Builder instructions.** How an AI agent builds it in this repo without breaking the site's rules.

If anything in this file conflicts with the older repo `CLAUDE.md`, **this file wins**. §B2 lists the specific stale lines.

---

# Part A: Scope

## A1. Why this upgrade

Search Console, July 5 to October 3, 2026: 20 clicks from 2,772 impressions. Demand is concentrated in four places:

| Demand | Signal | Response |
|---|---|---|
| "Who is on my ballot" | Query "who runnung for office in 19810 voting ballot": 150 impressions, average position about 8 | Full ballot (E1), plus an address-to-ballot lookup (E2) |
| Candidates and campaign finance | 13 of the 20 clicks | Every race, the same record shape for each (E1) |
| Drinking water | 822 impressions, position 50 to 65 | Water rebuild (Y2) |
| School report cards | About 130 impressions, position about 9, 0 clicks | Per-district report card pages and better snippets (Y3) |

Election work has a hard calendar. Year-round work turns the site into something people use every month.

## A2. Calendar (source: Department of Elections 2026 Election Calendar PDF)

| Date | Event | Must be live before |
|---|---|---|
| Sat Oct 10, 11:59 p.m. | Registration deadline | Done: `/vote/` shipped 2026-10-05 |
| Oct 6 / Oct 28 | 30-day and 8-day campaign finance report deadlines | E4 |
| Thu Oct 22 | Early voting opens (closed Oct 25, ends Nov 1) | E1, E2 by **Fri Oct 16** |
| Tue Nov 3 | General Election, polls 7 a.m. to 8 p.m. | E3 by **Wed Oct 21** |
| Thu Nov 5, 10 a.m. | Boards of Canvass certify results | E5 by **Fri Nov 6** |
| Tue Jan 12, 2027 | 154th General Assembly convenes | Y5 |
| May 2027 | School board elections | Y1 covers them |

## A3. Already shipped (2026-10-05)

- `/candidates/us-house/` corrected: Joseph "Dr. Joe" Arminio (R) added (commit `fa4b427`).
- `/vote/` How to Vote in Delaware 2026, plus a dated deadline banner (`assets/election-banner.js`, tested hour by hour through Nov 5) (`e062035`, `e791bc0`).
- The a11y CI now covers `/vote/` and the candidate pages. All 16 routes pass.

## A4. Election phase

### E1. The full 2026 ballot (ship by Fri Oct 16; thin records first, then E1b)

**Source:** `https://elections.delaware.gov/candidates/candidatelist/genl_fcddt_2026.html`. Plain `requests` can read it, no WAF. It is a single table with 128 rows (124 Qualified, 4 Withdrawn as of 2026-10-05). Columns: Office, County, Party, Candidate, Status, Filed. Each row is a `<tr>` with `<td data-label='...'>` cells. The candidate cell holds a `span.main-span` (the name) and a hidden `span.sub-span` with contact details. The page shows "Last Updated: YYYY-MM-DD HH:MM PM".

**Offices on the 2026 ballot:** U.S. Senator, Representative in Congress, Attorney General, State Treasurer, Auditor of Accounts, State Senator (Districts 1, 5, 7, 8, 9, 12, 13, 14, 15, 19, 20), State Representative (all 41 districts), New Castle County Council (districts), New Castle Recorder of Deeds, Register of Wills, Sheriff; Kent County Levy Court (at-large and districts), Recorder of Deeds, Sheriff; Sussex County Council (districts), Recorder of Deeds, Register of Wills, Sheriff.

**Published fields per candidate (Mark's decision: public-role fields only):** name as listed, office, district, county, party (expand "Ind Pty of DE" to "Independent Party of Delaware"), status (Qualified or Withdrawn), filing date, campaign website if listed, and for incumbents a link to their voting record. **Never published:** residential or mailing address, phone, email. The puller must not even write these to disk.

**Per race:** the candidate count and a dated withdrawals log. A race with one qualified candidate says so in plain words ("One qualified candidate is listed for this office"). Never call it "uncontested" or "safe".

**Pages:**
- `/candidates/` becomes the ballot index: every race grouped by level, each linking to its page. The existing FAQ stays.
- `/candidates/us-senate/`, `/candidates/attorney-general/`, `/candidates/state-treasurer/`, `/candidates/auditor/` (`/candidates/us-house/` already exists).
- `/candidates/state-senate/district-N/` for all 21 districts. The 10 not on the 2026 ballot (2, 3, 4, 6, 10, 11, 16, 17, 18, 21) were on the 2024 ballot, so their page says "This seat is not on the 2026 general election ballot. It was on the 2024 general election ballot; its next regular election is in 2028." and links the 2024 list as its source.
- `/candidates/state-house/district-N/` for all 41 districts.
- `/candidates/new-castle-county/`, `/candidates/kent-county/`, `/candidates/sussex-county/`: one page per county with every county race.

District and county pages are **static HTML generated by the build script**, not filled in by JavaScript, so search engines see the content. Each page gets a unique title and description ("Who is running for Delaware State House District 12 in 2026"), a canonical URL, BreadcrumbList JSON-LD, and a link to the state list.

**Incumbents:** match State House and State Senate candidates against `votes/data/votes-summary.json` (chamber + district, then last-name match). On a match, show the label "Incumbent" and link to `/votes/`. Statewide incumbents: Coons (U.S. Senate) and McBride (U.S. House) are listed; for AG, Treasurer and Auditor, confirm the incumbent from the officeholder's official state page before labelling. If a match can't be confirmed from a source, show no label.

**E1b (by Wed Oct 14): full records for the five statewide and federal races.** These get the same record shape as `/candidates/us-house/`: filing, biography facts from primary sources, a federal roll-call record where one exists, finance, and quoted, dated positions. U.S. Senate finance comes from the FEC (already in `campaign-finance/data`); state offices use state finance data only if E4 shows it can be read. Absences are stated, never left blank.

**Refresh:** a new workflow `candidates-daily.yml` runs the puller and the page generator daily at 11:00 UTC through 2026-11-04, then the schedule is removed. It commits `candidates/` only.

**Acceptance (all required):**
1. Each race's candidate count in `candidates/data/ballot-2026.json` equals the count in the source table on a fresh pull, and the total equals the source row count.
2. A PII gate finds zero matches in every file under `candidates/`: no phone pattern `\(?\d{3}\)?[ -.]\d{3}-\d{4}`, no "Residential Address", "Mailing Address" or "Email", no `cdn-cgi/l/email-protection`.
3. Every generated page renders its candidate names with JavaScript disabled (check the served HTML with `curl`).
4. All new pages are in `sitemap.xml`, the index page and `llms.txt`; a representative sample is in the a11y ROUTES, and CI passes.
5. Live production render checked in a real browser for: the index, one Senate district on the ballot, one Senate district not on it, one House district, one county page, one statewide page.
6. A Forge audit of the puller and the generator happens before the first production push of E1.

### E2. "Your 2026 ballot" address lookup (ship by Fri Oct 16)

A form on `/candidates/` (and later the homepage) takes a street address. A small Cloudflare Worker at `firststatelens.com/api/districts` sends it to the free U.S. Census Geocoder (`geographies/onelineaddress`, benchmark `Public_AR_Current`, vintage `Current_Current`, layers including 2026 State Legislative Districts Upper and Lower, the Congressional District and County). It returns `{ senate_district, house_district, county, matched_address }` and nothing else.

- The Worker writes no logs and does not store or cache addresses. Set observability off for the route and don't use `console.log`. CORS: same origin only.
- The page shows the matched address and every race on that voter's ballot, linked to the race pages. It always says "Confirm your districts and polling place at ivote.de.gov."
- ZIP-only input: show every House and Senate district that overlaps the ZIP (from a precomputed ZIP-to-district table built from Census relationship files) and ask for the street address to narrow it down.
- Fallback when the geocoder is down: a link to the state's district maps (`elections.delaware.gov/maps/`) and to ivote.de.gov. Never guess.

**Acceptance:** ten test addresses (at least three per county, including two near district lines) return the districts the state map shows; a Worker config read-back shows logs off; a nonsense address returns a clear "couldn't match this address" message; Forge audits the Worker.

### E3. Last result for this seat (ship by Wed Oct 21)

Each race page shows the raw vote count and percentage from the last general election for that seat (2024 for House, 2022 for the Senate seats up now), taken from the Department of Elections results archive. Give the parser **two hours**. If it doesn't parse cleanly, ship E3 for the statewide races only and log the rest. No "competitive", "safe" or margin labels.

### E4. State campaign finance filing status (decide by Oct 9, ship by Oct 21)

Probe for one hour: `elections.delaware.gov/candidates/campaignfinance/non_filers.html` and `cf_picfailedtofile.html` first, then CFRS. If a reliable, public, per-committee filed/not-filed record for the 30-day general report (due Oct 6) exists, show "30-day general report: on file as of [date]" or "not on file as of [date]" with the source link. If it doesn't, drop E4 and log the reason in `## Decisions`.

### E5. Certified results and the roster roll (Nov 5 to 6)

After the Boards of Canvass certify on Nov 5, publish per-race certified results on the race pages and a `/results/2026/` index. Then update the legislator roster in `/votes/` for the 154th General Assembly, and give each legislator a stable anchor or page so later links work. The deadline banner hides itself after Nov 5. Live election-night results are out of scope (Mark's decision).

## A5. Year-round phase (approved; starts after E5, in this order)

| # | Item | What it is | Data | Ship by |
|---|---|---|---|---|
| Y1 | Delaware Office Registry | Every elected office from U.S. Senate to school board and county row offices: term, current holder, next election year. Candidate pages check their claims against it. | Official state, county and school district pages; prior candidate lists | Nov 20 |
| Y2 | Water rebuild | Rebuild `/water/` around "is my water safe": per-water-system pages (violations, testing, contact), a "how to read a violation" header, lookup by address where service-area data exists | EPA SDWIS (already pulled); service areas if a source exists | Dec 4 |
| Y3 | School report card pages | One page per district ("Indian River School District report card"), better titles and snippets, educator salary by district folded in | DE Report Card (already pulled); Educator Salary `5tvj-rx46` | Dec 11 |
| Y4 | My Delaware, by address | E2 grows into the front door: your legislators and their votes, school district, water system, childcare near you, county, and your ballot in season | E2 Worker + existing datasets | Dec 18 |
| Y5 | Full-session bill tracker | Grow `/bill-tracker/` from SB 272 to every bill in the 154th General Assembly, sorted by date or number only, no curation | Open States | Jan 8, 2027 |
| Y6 | Childcare near me | A "licensed providers near me" view and a refreshed childcare dataset | FirstMap (needs Mark's Census key, arriving 2026-10-06; run locally, FirstMap blocks GitHub IPs) | Jan 15 |
| Y7 | Restaurant inspections | Raw violations by establishment and date in the state's own wording; no grades or scores; a how-to-read header saying a violation is not a closure | data.delaware.gov `384s-wygj` | Jan 29 |
| Y8 | Road safety | Crashes and fatalities by county and month | data.delaware.gov `827n-m6xc` | Feb 12 |
| Y9 | State contracts tab | A contracts tab on `/spending/` | data.delaware.gov `sifm-293u` | Feb 26 |
| Y10 | Reassessment, New Castle and Sussex | Same aggregate method as Kent | FOIA requests drafted 2026-10-05 (Mark sends them); blocked until records arrive | When data arrives |

## A6. Out of scope (killed, do not build)

- "Competitive", "safe" or "toss-up" labels, and any label computed from a margin.
- Live election-night results.
- Deep records for all 128 candidates before Nov 3. Thin and complete beats deep and partial.
- Republishing candidate addresses, phones or emails.
- Polling place assertions. We link to ivote.de.gov.
- An inmate population dashboard tied to the election.

## A7. Decisions log

| Date | Decision | By |
|---|---|---|
| 2026-10-05 | Mark is not attending ZipCode, so the full election slate goes ahead | Mark |
| 2026-10-05 | Public-role candidate fields only | Mark |
| 2026-10-05 | Certified results next day; no live election night | Mark |
| 2026-10-05 | Thin records for state and county races, full records for the 5 statewide/federal races | Mark |
| 2026-10-05 | Restaurant inspections raw and dated | Mark |
| 2026-10-05 | FOIA route for New Castle and Sussex reassessment | Mark |
| 2026-10-05 | All Part A pages approved, with year-round work after the election pages | Mark |
| 2026-10-05 | Address-lookup Worker with no logs; static per-district pages; one-hour E4 probe | Trazyn (reversible) |
| 2026-10-06 | **E4 dropped.** CFRS (cfrs.elections.delaware.gov) lists filed reports only through a session-bound legacy search grid (ASP.NET + Telerik, `ViewReportsList` needs server-side search state); there is no stable public feed. A missed scrape would publish a false "not on file" about a named candidate. State-office pages link to the CFRS public search instead. `non_filers.html` is a formal 15 Del. C. § 8044(i) penalty list, not per-report status, and is not republished. | Trazyn (per the E4 rule) |
| 2026-10-06 | Cato cross-vendor audit of E1 (codex gpt-6-astra): 2 HIGH + 3 MEDIUM, all fixed in `423a0c2` | Trazyn |
| 2026-10-06 | E2 shipped with the Forge/codex review folded (`661d058`): ZIP-only lookups answered from a bundled ZCTA overlap table (`worker/data/zip-districts.json`, rebuild via `worker/tools/zip_districts.py`); county district computed in the Worker with a 30 m near-line refusal; no coordinates returned. Platform rate limiting (Workers rate-limit binding or a WAF rule) NOT added: pricing unpublished, so it is Mark's call; the Worker has a best-effort per-isolate throttle and requires a same-site Origin. | Trazyn |
| 2026-10-06 | E1b shipped (`f45700a`): statewide full records rendered statically by the generator from `candidates/data/records/*.json` + FEC totals. Biographies limited to offices held on official pages; campaign self-descriptions excluded as not public records. | Trazyn |
| 2026-10-06 | a11y CI now triggers on candidates/, vote/, campaign-finance/, reassessment/ (`b9dabcf`); they had only been audited incidentally. | Trazyn |

---

# Part B: Instructions for the AI agent doing the building

Read all of Part B before touching code. It encodes mistakes that have already happened in this repo.

## B1. Read first, in this order

1. This file.
2. `SESSION-HANDOFF.md` (top section is the latest).
3. `ISA.md` (project system of record, slug `fsl-civic-suite`). Add each Part A item as ISCs before building it.
4. One existing page closest to what you are building (`candidates/us-house/index.html` for race pages, `vote/index.html` for prose pages, `reassessment/index.html` for data dashboards).

## B2. Repo facts (and stale instructions to ignore)

- **Static site, no build step.** Files at the repo root are served exactly as they are by a Cloudflare Workers static-assets deployment (`wrangler.jsonc`, no `main`). **A push to `main` deploys to production** within about a minute. There are no preview deploys of `main`. Treat every push as a release.
- `.assetsignore` keeps `etl/`, `scripts/`, `docs/`, `*.md`, `ISA.md` and `SESSION-HANDOFF.md` out of the public site. Anything new that must not be public goes there **before** the first push.
- Shared styles live in `assets/fsl.css`. **The homepage `index.html` does not load `fsl.css`**; it has its own inline styles. Any shared component added to the homepage needs its CSS duplicated inline there. (The 2026-10-05 banner failed a11y contrast because of this.)
- **ETL is Python** (`etl/sources/*.py`, run as `python -m etl.sources.<name> --out <dir>`, deps in `etl/requirements.txt`). That is the ratified pipeline for this repo, so new pullers stay in Python for consistency. **Browser-side scripts and the E2 Worker are JavaScript/TypeScript. Tests for JS use `bun test`.** Use bun, never npm/npx.
- The weekly refresh is `.github/workflows/refresh-all.yml`. A new puller needs a `run` line, an artifact path **and** an entry in the `git add` line, or its data never commits.
- The a11y gate is `scripts/a11y-audit.js` (`ROUTES` array) and runs in CI on every push (axe-core, WCAG 2.2 AA, serious/critical blocks).
- **Stale lines in the repo `CLAUDE.md`, ignore them:** "Removing the noindex meta ... soft-launch posture explicit" (the site is public and indexed; only `/clean-slate/` stays noindexed), "Workers: not in use" (E2 adds one, approved), and the dashboard list (out of date).

## B3. The neutrality rules (non-negotiable)

1. Every figure links to its primary public source and carries an as-of date.
2. Every candidate or entity in a set gets identical fields in identical order. Absences are stated in words ("No federal legislative record: has not held federal office"), never left blank.
3. No rankings, scores, grades, "winners", or labels computed from numbers. Order by a neutral key (ballot order, alphabetical, district number, date).
4. Party is a factual text label. No red/blue color coding. Accent colors for election pages are violet (candidates) and amber (dates).
5. Positions are quoted word for word with a date and source, never summarized.
6. When the state is the authority (elections, licensing), say so on the page and link to it. If our page and the state differ, the state is right and we fix the page.
7. Corrections repair the record. No rebuttals, no editorial notes.

## B4. Privacy rules

- Never write a private person's address, phone or email to disk, even into an intermediate file. Parse the field and drop it in memory.
- Candidate contact data from the state list is excluded (§A4 E1). The PII gate in E1 acceptance runs before every commit that touches `candidates/`.
- The E2 Worker stores nothing and logs nothing.
- Restaurant inspections (Y7) name businesses, which is approved. They never name individual employees.

## B5. Source access notes (learned the hard way)

- `elections.delaware.gov`: the candidate lists, `votereg.html`, `waystovote.html`, `votinglocations.html`, `/voter/absentee/` and the PDFs under `/public/calendar/pdfs/` all read fine with plain requests. `/elections/general/general.html` returns "Request Rejected" (WAF) to scripted **and** to WSLg Chrome requests. Use the calendar PDF instead. Don't hammer the site: at most one request every 2 seconds, and send the repo's User-Agent string (see `etl/sources/fec_de.py`).
- Census Geocoder: free, keyless, returns 2026 state legislative districts. Call it server-side from the Worker (no browser CORS).
- New Castle County GIS: "Token Required". The Sussex parcels path returns 404. Y10 waits on FOIA.
- FirstMap (childcare) times out from GitHub runners, so it runs locally with `CENSUS_API_KEY`.
- data.delaware.gov (Socrata): filter catalog searches with `domains=data.delaware.gov` (search is federated).

## B6. Page contract (copy from an existing page, don't invent)

Every new page has:
- `<title>` and meta description unique to the page.
- Canonical URL, the `robots: index, follow` meta, and the standard OG/Twitter tags with `/assets/og-image.png`.
- `assets/fsl.css` plus a small inline `<style>` setting `--accent-primary`.
- Topbar with the brand linking home, a title block (eyebrow, h1, sub), and the `.neutrality` "How to read this" box.
- Sections with `section-head` h2s, each figure followed by a `.src` source line.
- The standard footer with build line, links and the FirmSide AI line.
- JSON-LD: `Dataset` for data dashboards, `FAQPage` where there is a FAQ, `BreadcrumbList` on race pages.
- On election pages until Nov 5: the deadline banner markup plus `<script src="/assets/election-banner.js"></script>`.

Wire every new page in the same commit: homepage card (if it is a top-level dashboard), `sitemap.xml` (with `lastmod`), `llms.txt`, a11y `ROUTES` (at least one representative route per template), and `refresh-all.yml` or `candidates-daily.yml` if it has a puller.

## B7. Puller contract

- Module docstring: source URL, license, cadence, output files, neutrality posture, and how to run it.
- Retry with backoff on 5xx/429, identifying User-Agent, timeouts.
- **Silent-zero guard:** if the result is empty or implausibly small (for E1: fewer than 100 rows, or any statewide office missing), raise and write nothing.
- Writes `<out>/<name>.json` and `<out>/manifest.json` with `generated_at` (UTC ISO), the source URL, the source's own "last updated" stamp where it has one, and row counts.
- Deterministic output (sorted keys and stable order) so a no-change refresh produces no diff.
- Unit tests with `pytest` against a saved fixture of the source HTML, kept in `etl/tests/fixtures/`.

## B8. Verification ladder (do every rung, in order, and report the rung you reached)

1. **Unit tests:** `python -m pytest etl/tests -q` and `bun test scripts/`.
2. **Gates:** JSON validity (`jq empty`), the PII gate (§A4 E1-2), an em dash check on new copy (`rg '—|–|&mdash;|&ndash;'` must be empty), and an HTML parse check.
3. **Local render:** serve the repo root (`bunx --bun serve -l 8765 .`) and open pages with the Interceptor CLI.
   - Set the desktop width with `interceptor window resize` **only after confirming the window id holds your own tab**. There is one shared browser and other sessions use it. Restore any window you resized.
   - **Phone width:** don't resize the shared window. Inject a same-origin 390 px `<iframe>` of the page in your own tab with `interceptor eval --main`, then measure `scrollWidth` and any element wider than the frame.
   - `screenshot --pixel` can return a stale frame. If a screenshot doesn't match the DOM you just measured, trust the measurement and say so.
   - Close every tab you open (`interceptor tab close`). Tabs leak.
4. **Push** (this deploys). Poll the live URL with a cache-buster until the new content is there. Rollout takes up to about a minute, and different files arrive at different times.
5. **Live render** in the real browser on `https://firststatelens.com/...`: check content, the banner, zero failed requests.
6. **CI:** read the a11y run result for your commit (`gh run list` / `gh run view --log`). A red run blocks "done". Fix it and push again.
7. **Search check (after 48 hours, informational):** Search Console URL inspection of one new page, via Mark or the GSC API client in `~/answerable` (`bun run src/cli.ts gsc ...`).

"Done" means rungs 1 to 6 passed on production. If a rung could not be reached, say which one and why. Never write "should work".

## B9. Shell and git hygiene

- **Never `pkill -f <name>`.** It matches your own shell and kills the command (this happened 2026-10-05). Find the PID with `ps -eo pid,args` and kill it.
- Avoid long shell one-liners with apostrophes in quoted strings. Write content to a file with the editor tool and read it back.
- Always run `git pull --rebase` before committing. The `refresh-all` bot commits to `main` weekly and the daily candidates job will too.
- Conventional commits (`feat:`, `fix:`, `docs:`), each ending with the session's Co-Authored-By attribution lines.
- One commit per working change. Commit and push are part of each slice, not a follow-up.

## B10. Stop and ask Mark (don't decide alone)

- Any new label, category or framing that could read as a verdict.
- Any new data source containing personal information about private individuals.
- Any spend: paid APIs, new Cloudflare products beyond the Worker in E2, domains.
- Removing or rewording an existing published claim beyond a factual correction.
- Anything touching `/clean-slate/` (held).

Mark has approved everything else in Part A. Build it without asking again, report what shipped, and state the verification rung reached.

## B11. Reporting format (end of each item)

1. What shipped, with live URLs.
2. Commits.
3. The verification rung reached for each acceptance criterion, with evidence (counts, CI run, what the browser showed).
4. Anything deferred, with the reason and the follow-up date.
5. Updated `SESSION-HANDOFF.md` and `ISA.md`, pushed.

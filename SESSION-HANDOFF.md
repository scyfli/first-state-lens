# First State Lens — Session Handoff
**2026-07-09 · FirmSide AI Civic Analytics Lab · resume contract**

> Read this first, then `ISA.md` (project system of record, slug `fsl-civic-suite`).
> Vault context (methodology/sessions) lives separately: `first-state-lens-vault/11-Sessions/CONTEXT.md`.

---

## 2026-07-23 — Data refresh + FEC dashboard (LATEST · LIVE + PUBLIC)

**Commit:** `9330b0c` on `main`, pushed to `scyfli/first-state-lens`. Tree clean, 0 ahead. a11y CI **green** on this commit (all routes incl. new `/campaign-finance/`, 0 serious/critical).

**Mark's ask:** "update all dashboards, unblock the rest, get these pages up, find all data sources and make sure they have what we need end to end." Hold Clean Slate.

**Root cause found + fixed:** the 6 main dashboards were frozen at the 2026-06-15 build — NO CI workflow refreshed them (only bill-tracker + dgi ran on cron).

**What shipped (all live + render-verified):**
- **Keyless refresh** (`d6145a4`): Federal FY2024→**FY2025** (12,678 awards), Spending FY2025→**FY2026** ($17.03B), Water + Schools re-verified current. Render-verified Federal+Spending display new data.
- **`refresh-all.yml` CI workflow** (`7059e4e`) built + ran (run 30053107655 success → commit `0aecb85`): weekly Mon 09:00 UTC cron + manual dispatch; runs all pullers with existing CENSUS/OPENSTATES secrets + FEC secret, commits data back. **Votes refreshed live** (2026-07-23) via the OpenStates secret.
- **FEC Federal Campaign Finance dashboard** (`e450f8b`/`9330b0c`, ISC-45): **LIVE + PUBLIC** at `firststatelens.com/campaign-finance/`. 19 DE 2026 candidates, $11.53M raised (McBride $4.66M House, Coons $6.66M Senate). Strict-neutrality (raw filed numbers, party as factual label, NO ranking/colors/bars, FEC≠ballot caveat). `etl/sources/fec_de.py` (silent-zero guard) + page + homepage card + sitemap + a11y route + refresh-all wiring. `FEC_API_KEY` set as repo secret (Mark's api.data.gov key). **Live production render-verified.**
- **data.gov question answered:** `GSA/data.gov` repo = catalog website source (no datasets); the real lever = the free api.data.gov key (unlocks FEC), now in hand.

**IN-FLIGHT / open (next session):**
1. **Childcare did NOT refresh — blocked.** FirstMap GIS (`enterprise.firstmap.delaware.gov`) times out from GitHub cloud IPs (reachable from WSL in 0.08s). Childcare stays June-15 (low-harm, slow-changing, dated on-page). **Fix: run `firstmap_childcare` puller locally with the Census key** (needs Mark to provide CENSUS key — GitHub secret is write-only), or a self-hosted runner. **NEXT ACTION: get Census key → `CENSUS_API_KEY=… python3 -m etl.sources.firstmap_childcare --out childcare/data` locally → commit.**
2. **Neighbor bug flagged:** Candidates dashboard states "US Senate NOT up in 2026" but FEC shows a live 2026 DE Senate race (Coons). Coons's seat IS up Nov 2026 → the Candidates claim is likely wrong. Reconcile before it misleads.
3. **Still unbuilt (buildable, keyless/have-key):** DGI MMG county join finish; Reassessment-Kent (ISC-46).

**Rollback:** keyless refresh `git revert d6145a4`; FEC dashboard `git revert 9330b0c e450f8b` (removes /campaign-finance/, additive-only — the 8 live dashboards untouched); refresh-all workflow `git rm .github/workflows/refresh-all.yml`.

---

## 2026-07-14 — Candidate Reveal (LIVE + PUBLIC)

**Commit:** `3ed66c1` on `main`, pushed to `scyfli/first-state-lens`. Tree clean, 0 ahead.
**Verification:** 12/12 source URLs 200 (0 404s) · neutrality grep clean · real-browser render on **live** firststatelens.com/candidates/us-house/ (2 candidates, "About this slate" banner, no JS errors).

**What shipped:** the held 7/9 build flipped **public**. Re-pulled the final slate against the DE certified list (stamped "Updated 2026-07-14 07:56 PM", post noon deadline): **Sarah McBride is the only qualified candidate** for U.S. House at-large. **John Whalen III** (FEC-registered) did NOT make the DE ballot — kept (Mark's call) with a neutral sourced status ("Registered with the FEC; does not appear on the Delaware certified candidate list; not on the Nov 3 ballot"). Hold removed: `robots.txt` `Disallow /candidates/` dropped · `sitemap.xml` +3 candidate routes · homepage violet "Who's on the Ballot" card · us-house banner "not final"→"About this slate" · `candidates/index.html` FAQ+JSON-LD updated · `us-house.json`+`manifest.json` regenerated (final slate_note, generated_at 2026-07-14).

**In-flight:** none. Reveal complete + verified. Session ended on an advisory question.

**THE NEXT DECISION (Mark's pick):** which race next. Verified: the ONLY statewide/federal 2026 DE ballot races besides US House are **State Treasurer** (open seat, contested field) and **Auditor of Accounts** (York D inc). US Senate + AG + Governor + Lt Gov + Insurance are NOT up in 2026 (the plan wrongly listed US Senate + AG — corrected). Both remaining are executive (no roll-calls) but finance = manual state CFRS. **Trazyn rec:** Auditor first (smallest, proves CFRS path) → then Treasurer (open-seat, high value); OR build the ETL puller (FEC+Congress+LegiScan+CFRS) so races become "add JSON rows" (the spec's real scale step). State House/Senate districts + county = puller-scale, not same-day.

**Next session first action:** ask Mark which he picked (Auditor / Treasurer / puller); on Auditor, author the record (York filing + bio + CFRS finance + quoted positions; legislative_record absent = executive), link-check, neutrality grep, render-verify, add sitemap + homepage card, deploy.

**Rollback:** last known-good `3ed66c1` (reveal); prior held state `4e2412e`. To un-reveal: re-add `Disallow: /candidates/`, remove the 3 sitemap routes + homepage card, push.

---

## 2026-07-09 — Candidate Record slice (held build — superseded by the 7/14 reveal above)

**What shipped:** a new `/candidates/` section — the Candidate Stat Line, one standardized primary-sourced record rendered four ways (Explainer `/candidates/`, Compare + Docket `/candidates/us-house/`, Method `/candidates/method/`). One data contract `candidates/data/us-house.json`; all views read it. Slice target = **DE U.S. House at-large 2026**. Accent violet (neither-party). JSON-LD: Person/ItemList/FAQPage/CreativeWork.

**Data is real + verified:** McBride (incumbent, fully populated — 5 real 119th-Congress roll calls verified against House Clerk EVS XML, house.gov bio, one current-cycle sourced quote, FEC finance $3.92M) + Whalen (challenger — FEC-registered but NOT yet on the DE state list as of 7/9, stated plainly; FEC finance $0/$98; 2024-cycle quotes intentionally omitted). All 12 source URLs live-checked 200. Interceptor + production-parity render verified. Neutrality enforced in render: absence stated not blank, finance raw (no magnitude bars), positions quote-only.

**Commit:** `2e934ea` on `main`, pushed to `scyfli/first-state-lens`. Tree clean.

**HELD (deliberately):** `/candidates/*` is noindex (`_headers`) + Disallow (`robots.txt`) + NOT in sitemap + unlinked from homepage. Live-verified: `curl -sI https://firststatelens.com/candidates/us-house/` → `x-robots-tag: noindex`.

**⏰ NEXT ACTION (the July 14 flip — reminder set: Telegram cron 9am ET + Google Calendar email, both fire 7/14):**
1. After noon **July 14 2026** (filing deadline), re-pull the final DE US House candidate list (`elections.delaware.gov/candidates/candidatelist/genl_fcddt_2026.html`).
2. Confirm Whalen's ballot status; ADD any candidates who newly filed (author their record from primary sources, same fields).
3. Re-verify every source URL + McBride's votes.
4. **Public flip in one move:** remove the `/candidates/*` block from `_headers`, remove `Disallow: /candidates/` from `robots.txt`, add the 3 routes to `sitemap.xml`, add a homepage card. Then Interceptor live-verify + GSC.

**Scale step (after flip):** second office = a State Senate/House district → proves the harder LegiScan (roll-calls) + CFRS (finance) path. Full spec + data-source map: `~/.claude/PAI/MEMORY/WORK/20260709-fsl-midterm-ideate/SLICE-SPEC.md` (mirror `Desktop/TrazynOutPut/2026-07-09_fsl-candidate-statline/`).

**Rollback:** `git revert 2e934ea` removes the whole `/candidates/` section (held pages, additive-only — the 8 live dashboards untouched).

**Companion (separate repo, shipped):** firmsideai.com preview article `In Delaware, the ballot is the people` LIVE at `firmsideai.com/ballot-is-the-people` + Newsletter card (repo `FirmSideAI-Website` `44d10c6`); branded cover `ballot-og.png` (1280×720). LinkedIn newsletter draft + cover for Mark to post 7/10: `Desktop/TrazynOutPut/2026-07-09_fsl-candidate-statline/LINKEDIN-NEWSLETTER-v1.md`.

---

## 2026-06-22 — Public launch (prior context)

## Where we are (one paragraph)
**PUBLIC LAUNCH COMPLETE.** firststatelens.com is live in full public production. The six post-pivot dashboards (Schools, Water, Spending, Federal, Childcare, Votes) plus the homepage are public + indexable; DGI Food Access + Clean Slate are HELD (gated + noindex + robots-disallowed + unlinked) pending a de-advocacy rebuild. This session: found CI red and fixed it (a shared `color-contrast` defect — the per-KPI source citations + footer + in-table links all failed WCAG AA; one CSS pass turned all 6 green), ran a 9-page parallel content audit (the 6 new pages passed the neutrality rubric, the 2 oldest failed on advocacy framing + placeholder data → held), then executed the RED flip (removed noindex + the password gate from the 6, scoped noindex to the held dirs, added robots.txt + sitemap.xml, pulled the held cards + soft-launch copy from the homepage). All live-verified.

## Commit
- **HEAD: `d6b984e`** on `main`, pushed to `origin/main` (`scyfli/first-state-lens`). Tree clean.
- Session commits: `46d1fb8` a11y kpi-source contrast + widened CI paths · `0846928` a11y footer + base link color (a11y GREEN) · `fb397c1` ISA ISC-8 · `2e5b464` **PUBLIC LAUNCH flip** · `d6b984e` ISA D18/D19 launch record.
- **a11y CI GREEN** on the launch commit `2e5b464` (run 27980626995 = PASS, all 9 routes 0 serious/critical).

## Live-verified (2026-06-22)
- home / water / votes → 200, **no** X-Robots-Tag (indexable). dgi / clean-slate → 200, **noindex** (held).
- robots.txt + sitemap.xml → 200. water renders ungated with neutrality header. Homepage: 6 cards, 0 held-page links, 0 gate/soft-launch strings.

## In-flight / fast-follows (mostly Mark's manual)
1. **Google Search Console** — submit `https://firststatelens.com/sitemap.xml`. This is the actual "tell Google" step; site is public + indexable but undiscovered until submitted. (Mark)
2. **Delete `Desktop/First State Lens Keys.txt`** — sensitive file, still owed from 2026-06-15. (Mark)
3. **CI secret wiring** — add `OPENSTATES_API_KEY` + `FEC_API_KEY` as repo secrets + extend the ETL workflow to run those pullers (same as `CENSUS_API_KEY`). Until then Votes + Childcare serve their committed June-15 snapshots (accurate, dated). (ISA D16)
4. **Held-page rebuild — STATUS 2026-07-05:**
   - **DGI Food Access → LIVE + PUBLIC.** De-advocacy rewrite done (descriptive hero, neutrality header + firewall line, removed equity-test framing / parity scenarios / On-the-Record politician quotes / tone-danger KPIs / placeholder county bars), narrowed to real data (real Cycle-5 grant list + map layers + sourced MMG figures; hardcoded equity ratio dropped), password gate + noindex removed, un-held across robots.txt / _headers / sitemap.xml / homepage card. Live-verified indexable, neutrality grep clean. **Remaining (not blocking):** finish the MMG county join (Kent + New Castle real values) + grant-to-tract geocoding, then wire KPIs to a generated `data/*.json` instead of hardcoded HTML.
   - **Clean Slate → de-advocated but STILL HELD.** Copy rewritten neutral (killed the 47-year self-authored projection, the "promised/reprehensible/Promise-vs-Reality/What-Would-It-Take" framing, the advocacy quote wall; added an honest neutrality header that discloses there is no live feed). Kept noindex + gate. **Blocker to launch: it has no real dataset** — every figure is news-reported or self-projected. Needs a real DELJIS/SBI clearance source (FOIA or published report) before it can honestly go public.
   - Plus unbuilt **FEC campaign finance** (Wave 2 #2) + **Reassessment-Kent** (Wave 3).
5. **Homepage voice (my choices, pending Mark's review)** — status pill set to "LIVE · DELAWARE", footer to "PUBLIC RELEASE · FIRMSIDE AI · CIVIC ANALYTICS LAB". Reword if not his.

## Content artifacts shipped (not in this repo — `Desktop/TrazynOutPut/2026-06-22_fsl-article/`)
- `FSL-header.png` — 1280×720 titled header image built from the real logo ("Data to the People").
- `ARTICLE-v1.md` — 514-word equity-mission article with all 6 dashboard links (M14 + condescension gates clean).
- `POST-FOR-ARTICLE.md` — 167-word LinkedIn post that runs the article.
- `2026-06-22_fsl-linkedin-nonprofits/POST-v1.md` — earlier nonprofit-first teaser post.
- Open: Mark publishes the article (cover = FSL-header.png) then the post; optional hashtag set; optional 2x image re-render.

## Next action (in order)
1. If continuing FSL build: pick up the **held-page rebuild** (DGI + Clean Slate to the neutrality standard) OR build **FEC campaign finance** (data.gov key in the keys file; probe `api.open.fec.gov` before building, per the probe-before-build pattern).
2. Wire the two CI secrets (#3 above) so Votes/Childcare refresh.
3. Nudge Mark on the manual fast-follows (GSC, keys-file deletion).

## Rollback envelope
- Need to un-launch (re-gate everything)? `git revert 2e5b464` restores noindex + the password gate on the 6 + the soft-launch homepage. Held pages were untouched by the flip, so they're unaffected.
- a11y contrast fix bad? `git revert 0846928 46d1fb8` (bars/citations revert to the low-contrast color; not a crash).
- DGI pipeline untouched all session (additive-only invariant held).

## Verify on resume
- `git status` clean; `git log origin/main -1` = `d6b984e` (or later).
- Live: `curl -sI https://firststatelens.com/ | grep -i x-robots` → absent (public); `curl -sI https://firststatelens.com/dgi-food-access/ | grep -i x-robots` → noindex (held).
- a11y CI green on HEAD; DGI ETL cron green (last run 2026-06-21).

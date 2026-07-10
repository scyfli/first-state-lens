# First State Lens — Session Handoff
**2026-07-09 · FirmSide AI Civic Analytics Lab · resume contract**

> Read this first, then `ISA.md` (project system of record, slug `fsl-civic-suite`).
> Vault context (methodology/sessions) lives separately: `first-state-lens-vault/11-Sessions/CONTEXT.md`.

---

## 2026-07-09 — Candidate Record slice (LATEST, held build)

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

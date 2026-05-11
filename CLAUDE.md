# CLAUDE.md — first-state-lens (public dashboard frontend)

> Public frontend repo for First State Lens dashboards. The analytical CMS, methodology source-of-truth, briefs, and source registry live in a separate **private** vault repo (`scyfli/first-state-lens-vault`). That repo's CLAUDE.md is the master operating agreement; this file is the deploy-and-frontend addendum.

## Where the audit trail lives

The vault is the single source of truth for *why*. Session-by-session reasoning, ratified decisions, methodology revisions, distribution sequence, FOIA queue, and stakeholder context all live in the vault under `11-Sessions/` (handoff trio), `07-Briefs/`, `05-Methodology/`, and `04-Sources/`. This repo carries the *what*: runnable code, the static HTML dashboards, and the ETL pipeline.

When working in this repo, descriptive commit messages and PR descriptions are the audit trail surface. They should reference the vault brief / methodology version / session log that motivated the change, e.g. *"per design brief 2026-05-11-DGI-Bulk-ETL-Design (vault session-13)."* The vault's hardened handoff discipline (session-state-check + CONTEXT.md regeneration + worktree merge-back) does NOT replicate here — it would double maintenance overhead with no audit-trail gain.

Anyone resuming work in this repo without vault access should treat the PR history + commit log as authoritative. Anyone with vault access should always read the vault's CONTEXT.md first.

## What this repo is

Cloudflare Pages-deployed monorepo:

- `/` — landing page (`index.html`)
- `/clean-slate/` — Clean Slate Implementation Tracker (SB 111 / SB 112)
- `/dgi-food-access/` — DGI Food Access Tracker (SB 254)

Each dashboard is a single-file HTML + Chart.js page (no build step at v1.0). Geospatial (MapLibre + static GeoJSON) lands at the v1.0 deploy of the DGI dashboard.

## Hosting

- **Production:** Cloudflare Pages, custom domain `firststatelens.com`
- **DNS:** Cloudflare (delegated nameservers)
- **HTTPS:** Cloudflare auto-managed
- **R2:** for bulk-data downloads and PMTiles when DGI map lands
- **Workers:** reserved for future server-side password gating; not in use at v1.0

## Soft-launch gating

Each dashboard ships with a client-side JS password gate (SHA-256 hash baked into the HTML; correct password unlocks; sessionStorage caches the unlock). Threat model: "keep crawlers and casual visitors out." Not "stop a determined attacker"; view-source bypassable.

- Clean Slate password: in user's password manager (NOT in this repo)
- DGI password: in user's password manager (NOT in this repo)
- **The hashes are public** (visible in the HTML source). This is intentional — hashes are one-way; the published hash does not leak the password. Brute-forcing a 20-char random base64 password against SHA-256 is computationally infeasible.

To rotate either password:
1. Generate new password
2. Compute SHA-256: `node -e "console.log(require('crypto').createHash('sha256').update('NEW_PASSWORD').digest('hex'))"`
3. Edit `clean-slate/index.html` or `dgi-food-access/index.html`: replace the `HASH` constant
4. Bump `STORAGE_KEY` so previously-unlocked sessions re-prompt (e.g., `fsl-gate-2026-05` → `fsl-gate-2026-06`)
5. Commit + push; Cloudflare Pages auto-deploys
6. Update password in password manager

## Deploy

- **Trigger:** push to `main` → Cloudflare Pages picks up via GitHub integration → auto-deploys
- **Preview:** every PR gets a preview URL automatically
- **Build command:** none (static site)
- **Build output directory:** `/` (repo root)
- **Health check:** GET `/` returns 200; GET `/clean-slate/` returns 200; GET `/dgi-food-access/` returns 200

## Pre-merge checklist (per CLAUDE.md from vault repo)

1. `/file-integrity-guard` — passes (HTML well-formed)
2. Methodology page in the vault has `publish: true` for any dashboard being deployed (deploy gate)
3. Methodology version in dashboard footer matches the vault's methodology version
4. axe-core + Lighthouse pass (WCAG 2.2 AA) — CI configured after first deploy lands
5. Perma.cc snapshot for tagged releases

## Versioning convention

- Patch deploys: minor copy/styling tweaks, no methodology change
- Minor deploys: methodology version bump (e.g., MMG data refresh), still autonomous
- Major deploys: hero KPI framing change — requires explicit user confirmation per vault CLAUDE.md

## What does NOT belong in this repo

- Source notes (live in vault)
- Methodology markdown (lives in vault; mirrored separately to `methodology.firststatelens.com` via Quartz when configured)
- Briefs, FOIA drafts, session logs (vault)
- Passwords or password hashes for *other* dashboards not deployed here
- Internal-only analytical work

## Forbidden suggestions

(Mirroring the vault's CLAUDE.md.)

- **Next.js / React frameworks for v1.0** — static HTML + Chart.js is the ratified choice. Astro lands when the third dashboard forces shared-component reuse.
- **Server-side rendering** for the dashboards — they're static.
- **Removing the noindex meta** from the dashboards or the `X-Robots-Tag` header — soft-launch posture explicit.
- **Repurposing this repo as a dashboard backend** — it's a frontend monorepo; backend (ETL, Datasette) is separate.

---

*Last revised: 2026-05-11 · Part of First State Lens · FirmSide AI · Civic Analytics Lab*

# First State Lens

**Civic Outcomes Atlas · Delaware**

A suite of dashboards tracking the gap between Delaware legislative intent and on-the-ground reality across signature programs.

> Soft-launch preview. The dashboards on this site are password-gated during the soft-launch period. Live URL: <https://firststatelens.com>

## Dashboards

| Dashboard | Status | Focus |
|---|---|---|
| **Clean Slate Implementation Tracker** | Live (gated) | SB 111 / SB 112 automatic expungement throughput vs. statutory promise |
| **DGI Food Access Tracker** | Scaffold (gated) | SB 254 Delaware Grocery Initiative deployment vs. food-insecurity need |

## What this repo is

Public frontend code for the First State Lens dashboards. Single-file HTML + Chart.js for each dashboard, served from Cloudflare Pages.

**This repo is intentionally narrow.** It contains the public-facing dashboard code only. The analytical CMS — methodology source-of-truth, source registry, lineage graph, briefs — lives in a separate private repo. Each published number on these dashboards traces to a methodology page; methodology pages will be mirrored to `methodology.firststatelens.com` (forthcoming).

## Architecture

- **Hosting:** Cloudflare Pages + R2
- **Renderer:** Single-file HTML + Chart.js per dashboard (no build step at v1.0)
- **Geospatial (DGI):** Static GeoJSON + MapLibre at v1.0 deploy (deferred from scaffold)
- **Accessibility floor:** WCAG 2.2 AA
- **Soft-launch gate:** client-side JS password gate; each dashboard has an independent password

## Methodology

Each dashboard's methodology page traces every published number to its source.

- Clean Slate methodology: `methodology.firststatelens.com/clean-slate/` (forthcoming via Quartz mirror)
- DGI Food Access methodology: `methodology.firststatelens.com/dgi-food-access/` (forthcoming)

Methodology is versioned. Every published number is sealed with `methodology vX.Y.Z · sealed YYYY-MM-DD · perma.cc/XXXX-YYYY` in the dashboard footer.

## Branding

Built by **FirmSide AI · Civic Analytics Lab**. The brand is deliberately decoupled from any single stakeholder.

## License

Code in this repo is MIT licensed (see `LICENSE`). Data and methodology are separately governed; see the methodology pages for source citations and licensing per source.

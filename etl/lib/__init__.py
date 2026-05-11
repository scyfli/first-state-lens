"""Shared infrastructure for the DGI Food Access ETL.

Documented extension of the design brief's directory layout. The brief
specifies data-flow modules (sources/transforms/outputs); shared
infrastructure code those modules import lives here.

Modules:
  fetch       — HTTP client with retries, UA, timeout (etl.lib.fetch)
  atomic_io   — write-temp-then-rename + last_fetched stamping
  manifest    — manifest.json builder (per-resource last_fetched + sha256)
  validate    — datapackage validation wrapper
"""

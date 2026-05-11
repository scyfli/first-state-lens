"""Per-source pullers for the DGI Food Access ETL.

Each puller is a self-contained module that:
  1. Knows the canonical URL / endpoint for its source
  2. Issues an HTTP request via etl.lib.fetch (retries + UA + timeout)
  3. Persists the raw response to etl/raw/<source-name>.<ext> atomically
  4. Returns a ResourceFetchResult with last_fetched, sha256, source URL,
     HTTP status, and any parse warnings — which the orchestrator aggregates
     into manifest.json and datapackage.json

Pullers MUST be runnable in isolation:
  python -m etl.sources.<puller> --out etl/raw/
"""

"""Output writers for the DGI Food Access ETL.

Produces:
  - dgi-food-access/data/datapackage.json   (Frictionless contract)
  - dgi-food-access/data/manifest.json      (lightweight freshness cousin)
  - dgi-food-access/data/<resource>.csv|.geojson  per design brief

S+1: scaffold only. Implementation lands in S+3 alongside transforms.
"""

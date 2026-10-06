# Rebuild worker/data/zip-districts.json (ZIP -> State Senate / House overlap).
# Inputs (download first, into the working directory):
#   zcta.geojson : TIGERweb PUMA_TAD_TAZ_UGA_ZCTA/MapServer/1/query?where=ZCTA5 LIKE '197%' OR '198%' OR '199%'&outFields=ZCTA5&outSR=4326&f=geojson
#   fm1.geojson / fm2.geojson : FirstMap Boundaries/DE_Political_Boundaries/FeatureServer/{1,2}/query?where=1=1&outFields=DISTRICT&outSR=4326&f=geojson
# Run: uv run --no-project --with shapely --with pyproj python worker/tools/zip_districts.py  (writes zip-districts.json; copy to worker/data/)

# Build ZIP (ZCTA) -> State Senate / State House district overlap table.
# A district is listed for a ZIP when it covers at least 1% of the ZIP's area (drops
# boundary slivers from mismatched source geometries). Areas use an equal-area projection.
import json
from shapely.geometry import shape
from shapely.ops import transform
from pyproj import Transformer

T = Transformer.from_crs("EPSG:4326", "EPSG:5070", always_xy=True).transform
def load(p, key):
    out = []
    for f in json.load(open(p))["features"]:
        g = transform(T, shape(f["geometry"])).buffer(0)
        out.append((f["properties"][key], g))
    return out

z = load("zcta.geojson", "ZCTA5")
sd = load("fm1.geojson", "DISTRICT")
hd = load("fm2.geojson", "DISTRICT")
MIN_SHARE = 0.01
table = {}
for zc, zg in sorted(z):
    if zg.area == 0:
        continue
    def hits(polys):
        r = []
        for d, g in polys:
            if not zg.intersects(g):
                continue
            share = zg.intersection(g).area / zg.area
            if share >= MIN_SHARE:
                r.append((int(d), round(share, 3)))
        return sorted(r)
    s, h = hits(sd), hits(hd)
    if not s and not h:
        continue  # ZCTA with no Delaware district (outside the state)
    table[zc] = {"senate": [d for d, _ in s], "house": [d for d, _ in h]}
out = {
    "source": {
        "zcta": "U.S. Census Bureau, 2020 ZIP Code Tabulation Areas (TIGERweb)",
        "districts": "Delaware FirstMap, DE_Political_Boundaries layers 1 (Senate) and 2 (House)",
        "method": "District listed when it covers at least 1% of the ZIP area (EPSG:5070 equal-area). ZCTAs approximate USPS ZIP codes.",
        "built": "2026-10-06",
    },
    "zips": table,
}
json.dump(out, open("zip-districts.json", "w"), separators=(",", ":"))
multi = sum(1 for v in table.values() if len(v["house"]) > 1)
print(len(table), "ZIPs;", multi, "span more than one House district")
print("19810:", table.get("19810"), "19901:", table.get("19901"), "19971:", table.get("19971"))

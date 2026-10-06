/*
 * First State Lens: "Your 2026 ballot" district lookup (docs/UPGRADE-PLAN.md, E2).
 *
 * POST /api/districts  { "address": "<one-line street address>" }
 *   -> { status: "ok", matched_address, senate_district, house_district, county,
 *        county_district, near_county_line }
 * POST /api/districts  { "zip": "19810" }
 *   -> { status: "zip", zip, senate_districts: [...], house_districts: [...] }
 * Errors: { status: "no_match" | "not_delaware" | "bad_request" | "unavailable" | "busy", message }
 *
 * Street addresses are forwarded once to the U.S. Census Bureau geocoder
 * (geographies/onelineaddress, benchmark Public_AR_Current, vintage Current_Current,
 * layers 56 = State Legislative Districts Upper, 58 = Lower, 82 = Counties), which sends
 * no CORS headers, so a browser cannot call it directly. That request carries the address
 * in its query string to the Census Bureau, which keeps its own server records.
 * ZIP-only lookups never leave this Worker: they read the bundled ZIP table.
 *
 * Privacy on our side: nothing is stored, cached or logged. There is no console output in
 * this file, observability (logs, invocation logs, traces) is disabled in wrangler.jsonc,
 * responses are Cache-Control: no-store, the browser sends the address in a POST body,
 * and the response carries district numbers, not coordinates.
 *
 * County council / levy court district: point-in-polygon against Delaware FirstMap
 * boundaries bundled here (data/county-districts.json). Points within NEAR_LINE_M of a
 * boundary are reported as near_county_line instead of guessing.
 *
 * Every other path is served by the static assets binding; wrangler.jsonc routes only
 * /api/* here (run_worker_first).
 */
import COUNTY_DISTRICTS from "./data/county-districts.json";
import ZIP_TABLE from "./data/zip-districts.json";

const GEOCODER = "https://geocoding.geo.census.gov/geocoder/geographies/onelineaddress";
const ALLOWED_ORIGINS = new Set(["https://firststatelens.com", "https://www.firststatelens.com"]);
const COUNTY_FIPS = { "001": "Kent", "003": "New Castle", "005": "Sussex" };
const MAX_LEN = 200;
const MAX_BODY = 2048;
const NEAR_LINE_M = 30;
// Best-effort, per-isolate throttle (Cloudflare runs many isolates, so this only blunts
// bursts from one client; a platform rate limit is a separate, owner-approved step).
const THROTTLE_MAX = 12;
const THROTTLE_WINDOW_MS = 60_000;
const hits = new Map();

const HEADERS = {
  "content-type": "application/json; charset=utf-8",
  "cache-control": "no-store",
  "x-content-type-options": "nosniff",
  "referrer-policy": "no-referrer",
};

function reply(body, status = 200, extra = {}) {
  return new Response(JSON.stringify(body), { status, headers: { ...HEADERS, ...extra } });
}

function districtNumber(rec, field) {
  const v = rec && (rec[field] ?? rec.BASENAME);
  const n = parseInt(String(v ?? ""), 10);
  return Number.isInteger(n) && n > 0 ? n : null;
}

function layer(geos, suffix) {
  const key = Object.keys(geos).find((k) => k.endsWith(suffix));
  return key ? (geos[key] || [])[0] : undefined;
}

// ---- geometry (lon/lat degrees; distances via local equirectangular metres) ----
function inRing(x, y, ring) {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i];
    const [xj, yj] = ring[j];
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}
function polygons(g) {
  if (!g) return [];
  if (g.type === "Polygon") return [g.coordinates];
  if (g.type === "MultiPolygon") return g.coordinates;
  return [];
}
function inGeom(x, y, g) {
  return polygons(g).some((p) => inRing(x, y, p[0]) && !p.slice(1).some((h) => inRing(x, y, h)));
}
function segDistM(x, y, a, b) {
  const kx = 111320 * Math.cos((y * Math.PI) / 180);
  const ky = 110540;
  const ax = (a[0] - x) * kx, ay = (a[1] - y) * ky, bx = (b[0] - x) * kx, by = (b[1] - y) * ky;
  const dx = bx - ax, dy = by - ay;
  const len2 = dx * dx + dy * dy;
  const t = len2 === 0 ? 0 : Math.max(0, Math.min(1, -(ax * dx + ay * dy) / len2));
  const px = ax + t * dx, py = ay + t * dy;
  return Math.sqrt(px * px + py * py);
}
function edgeDistM(x, y, g) {
  let best = Infinity;
  for (const p of polygons(g)) for (const ring of p)
    for (let i = 1; i < ring.length; i++) best = Math.min(best, segDistM(x, y, ring[i - 1], ring[i]));
  return best;
}

/** Pure: county council / levy court district for a point, or near-line / unknown. */
export function countyDistrict(county, lon, lat, geo = COUNTY_DISTRICTS) {
  if (!Number.isFinite(lon) || !Number.isFinite(lat)) return { district: null, near_line: false };
  const feats = (geo.features || []).filter((f) => f && f.properties && f.properties.county === county && polygons(f.geometry).length);
  const inside = feats.filter((f) => inGeom(lon, lat, f.geometry));
  const near = feats.some((f) => edgeDistM(lon, lat, f.geometry) < NEAR_LINE_M);
  if (inside.length === 1 && !near) return { district: inside[0].properties.district, near_line: false };
  return { district: null, near_line: inside.length > 1 || near };
}

/** Pure: turn a Census geocoder JSON payload into our response body. */
export function interpret(payload) {
  const match = payload?.result?.addressMatches?.[0];
  if (!match) {
    return { status: "no_match", message: "We couldn't match that address. Check the street number and town." };
  }
  const g = match.geographies || {};
  const upper = layer(g, "State Legislative Districts - Upper");
  const lower = layer(g, "State Legislative Districts - Lower");
  const county = (g["Counties"] || [])[0];
  const state = county?.STATE ?? upper?.STATE ?? lower?.STATE;
  if (state !== "10") {
    return { status: "not_delaware", message: "That address doesn't appear to be in Delaware." };
  }
  const senate = districtNumber(upper, "SLDU");
  const house = districtNumber(lower, "SLDL");
  const countyName = COUNTY_FIPS[county?.COUNTY];
  if (!senate || !house || !countyName || senate > 21 || house > 41) {
    return { status: "no_match", message: "We found the address but not all of its districts." };
  }
  const cd = countyDistrict(countyName, Number(match.coordinates?.x), Number(match.coordinates?.y));
  return {
    status: "ok",
    matched_address: String(match.matchedAddress || ""),
    senate_district: senate,
    house_district: house,
    county: countyName,
    county_district: cd.district,
    near_county_line: cd.near_line,
  };
}

/** Pure: ZIP-only answer from the bundled ZCTA overlap table. */
export function zipLookup(zip, table = ZIP_TABLE) {
  const row = table.zips?.[zip];
  if (!row) return { status: "not_delaware", message: "That ZIP code isn't one we have for Delaware." };
  return { status: "zip", zip, senate_districts: row.senate, house_districts: row.house };
}

/** Pure: validate the request body; returns { address } or { zip } or null. */
export function cleanInput(body) {
  if (typeof body?.zip === "string") {
    const z = body.zip.replace(/\s+/g, "");
    return /^\d{5}$/.test(z) ? { zip: z } : null;
  }
  const a = typeof body?.address === "string" ? body.address.replace(/\s+/g, " ").trim() : "";
  if (a.length < 6 || a.length > MAX_LEN || !/\d/.test(a) || !/[a-z]/i.test(a)) return null;
  return { address: a };
}

function throttled(ip, now = Date.now()) {
  if (!ip) return false;
  const rec = hits.get(ip);
  if (!rec || now - rec.start > THROTTLE_WINDOW_MS) {
    hits.set(ip, { start: now, n: 1 });
    if (hits.size > 5000) hits.clear();
    return false;
  }
  rec.n += 1;
  return rec.n > THROTTLE_MAX;
}

async function districts(request, fetchImpl, devOrigin) {
  if (request.method !== "POST") return reply({ status: "bad_request", message: "Use POST." }, 405, { allow: "POST" });
  const origin = request.headers.get("origin");
  if (!origin || !(ALLOWED_ORIGINS.has(origin) || (devOrigin && origin === devOrigin))) return reply({ status: "bad_request", message: "Not allowed." }, 403);
  const site = request.headers.get("sec-fetch-site");
  if (site && site !== "same-origin") return reply({ status: "bad_request", message: "Not allowed." }, 403);
  if (!(request.headers.get("content-type") || "").toLowerCase().startsWith("application/json")) {
    return reply({ status: "bad_request", message: "Send JSON." }, 415);
  }
  const declared = Number(request.headers.get("content-length"));
  if (!Number.isFinite(declared) || declared <= 0 || declared > MAX_BODY) {
    return reply({ status: "bad_request", message: "Request too large." }, 413);
  }
  const raw = await request.text();
  if (raw.length > MAX_BODY) return reply({ status: "bad_request", message: "Request too large." }, 413);
  if (throttled(request.headers.get("cf-connecting-ip"))) {
    return reply({ status: "busy", message: "Too many lookups in a short time. Wait a minute and try again." }, 429);
  }
  let body;
  try {
    body = JSON.parse(raw);
  } catch {
    return reply({ status: "bad_request", message: "Send JSON with an address." }, 400);
  }
  const input = cleanInput(body);
  if (!input) {
    return reply({ status: "bad_request", message: "Enter a street address with a house number, for example 411 Legislative Ave, Dover, DE." }, 400);
  }
  if (input.zip) return reply(zipLookup(input.zip));
  const url = new URL(GEOCODER);
  url.searchParams.set("address", input.address);
  url.searchParams.set("benchmark", "Public_AR_Current");
  url.searchParams.set("vintage", "Current_Current");
  url.searchParams.set("layers", "56,58,82");
  url.searchParams.set("format", "json");
  let payload;
  try {
    const res = await fetchImpl(url.toString(), { signal: AbortSignal.timeout(12000), headers: { "user-agent": "FirstStateLens/1.0 (+https://firststatelens.com)" } });
    if (!res.ok) throw new Error(String(res.status));
    payload = await res.json();
  } catch {
    return reply({ status: "unavailable", message: "The Census address lookup isn't responding right now." }, 503);
  }
  return reply(interpret(payload));
}

export default {
  async fetch(request, env) {
    const { pathname } = new URL(request.url);
    if (pathname === "/api/districts") return districts(request, fetch, env && env.DEV_ORIGIN);  // DEV_ORIGIN: wrangler dev --var only, never set in production
    if (pathname.startsWith("/api/")) return reply({ status: "bad_request", message: "Not found." }, 404);
    return env.ASSETS.fetch(request);
  },
};

export { districts as _districtsForTest, throttled as _throttledForTest };

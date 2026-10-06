/*
 * First State Lens: "Your 2026 ballot" district lookup (docs/UPGRADE-PLAN.md, E2).
 *
 * POST /api/districts  { "address": "<one-line street address>" }
 *   -> { status: "ok", matched_address, senate_district, house_district, county, lon, lat }
 *   -> { status: "no_match" | "not_delaware" | "bad_request" | "unavailable", message }
 *
 * The address is forwarded once to the U.S. Census Bureau geocoder (geographies/
 * onelineaddress, benchmark Public_AR_Current, vintage Current_Current, layers 56 = 2026
 * State Legislative Districts Upper, 58 = Lower, 82 = Counties) because that service sends
 * no CORS headers, so a browser cannot call it directly.
 *
 * Privacy: nothing is stored, cached or logged. There is no console output in this file,
 * observability is disabled in wrangler.jsonc, responses are Cache-Control: no-store, and
 * the address travels in a POST body, never in a URL.
 *
 * Every other path is served by the static assets binding; wrangler.jsonc routes only
 * /api/* here (run_worker_first).
 */

const GEOCODER = "https://geocoding.geo.census.gov/geocoder/geographies/onelineaddress";
const ALLOWED_ORIGINS = new Set(["https://firststatelens.com", "https://www.firststatelens.com"]);
const COUNTY_FIPS = { "001": "Kent", "003": "New Castle", "005": "Sussex" };
const MAX_LEN = 200;

const HEADERS = {
  "content-type": "application/json; charset=utf-8",
  "cache-control": "no-store",
  "x-content-type-options": "nosniff",
  "referrer-policy": "no-referrer",
};

function reply(body, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: HEADERS });
}

function districtNumber(rec, field) {
  const v = rec && (rec[field] ?? rec.BASENAME);
  const n = parseInt(String(v ?? ""), 10);
  return Number.isInteger(n) && n > 0 ? n : null;
}

/** Pure: turn a Census geocoder JSON payload into our response body. */
export function interpret(payload) {
  const match = payload?.result?.addressMatches?.[0];
  if (!match) {
    return { status: "no_match", message: "We couldn't match that address. Check the street number and town, or look it up at ivote.de.gov." };
  }
  const g = match.geographies || {};
  const upper = (g["2026 State Legislative Districts - Upper"] || [])[0];
  const lower = (g["2026 State Legislative Districts - Lower"] || [])[0];
  const county = (g["Counties"] || [])[0];
  const state = county?.STATE ?? upper?.STATE ?? lower?.STATE;
  if (state !== "10") {
    return { status: "not_delaware", message: "That address doesn't appear to be in Delaware." };
  }
  const senate = districtNumber(upper, "SLDU");
  const house = districtNumber(lower, "SLDL");
  const countyName = COUNTY_FIPS[county?.COUNTY];
  if (!senate || !house || !countyName || senate > 21 || house > 41) {
    return { status: "no_match", message: "We found the address but not all of its districts. Look it up at ivote.de.gov." };
  }
  const lon = Number(match.coordinates?.x);
  const lat = Number(match.coordinates?.y);
  return {
    status: "ok",
    matched_address: String(match.matchedAddress || ""),
    senate_district: senate,
    house_district: house,
    county: countyName,
    lon: Number.isFinite(lon) ? Math.round(lon * 1e5) / 1e5 : null,
    lat: Number.isFinite(lat) ? Math.round(lat * 1e5) / 1e5 : null,
  };
}

/** Pure: validate the request body; returns the cleaned address or null. */
export function cleanAddress(body) {
  const a = typeof body?.address === "string" ? body.address.replace(/\s+/g, " ").trim() : "";
  if (a.length < 6 || a.length > MAX_LEN || !/\d/.test(a) || !/[a-z]/i.test(a)) return null;
  return a;
}

async function districts(request, fetchImpl) {
  if (request.method !== "POST") return reply({ status: "bad_request", message: "Use POST." }, 405);
  const origin = request.headers.get("origin");
  if (origin && !ALLOWED_ORIGINS.has(origin)) return reply({ status: "bad_request", message: "Not allowed." }, 403);
  let body;
  try {
    body = await request.json();
  } catch {
    return reply({ status: "bad_request", message: "Send JSON with an address." }, 400);
  }
  const address = cleanAddress(body);
  if (!address) {
    return reply({ status: "bad_request", message: "Enter a street address with a house number, for example 411 Legislative Ave, Dover, DE." }, 400);
  }
  const url = new URL(GEOCODER);
  url.searchParams.set("address", address);
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
    return reply({ status: "unavailable", message: "The Census address lookup isn't responding right now. Try again, or look up your districts at ivote.de.gov." }, 503);
  }
  return reply(interpret(payload));
}

export default {
  async fetch(request, env) {
    const { pathname } = new URL(request.url);
    if (pathname === "/api/districts") return districts(request, fetch);
    if (pathname.startsWith("/api/")) return reply({ status: "bad_request", message: "Not found." }, 404);
    return env.ASSETS.fetch(request);
  },
};

export { districts as _districtsForTest };

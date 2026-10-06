// bun test worker/
import { describe, expect, test } from "bun:test";
import worker, { interpret, cleanInput, countyDistrict, zipLookup, _districtsForTest, _throttledForTest } from "./index.js";

const fx = (n) => Bun.file(new URL(`./fixtures/${n}.json`, import.meta.url)).json();

describe("interpret (Census payload -> our answer)", () => {
  test("Legislative Hall, Dover: districts, county district, no coordinates", async () => {
    const r = interpret(await fx("legislative-hall"));
    expect(r).toMatchObject({ status: "ok", senate_district: 17, house_district: 32, county: "Kent", county_district: 2, near_county_line: false });
    expect(r.matched_address).toContain("LEGISLATIVE AVE");
    expect(r).not.toHaveProperty("lon");
    expect(r).not.toHaveProperty("lat");
  });
  test("an address outside Delaware is refused", async () => {
    expect(interpret(await fx("not-delaware")).status).toBe("not_delaware");
  });
  test("no match", async () => {
    expect(interpret(await fx("no-match")).status).toBe("no_match");
  });
  test("impossible district numbers are refused", async () => {
    const p = await fx("legislative-hall");
    p.result.addressMatches[0].geographies["2026 State Legislative Districts - Lower"][0].SLDL = "099";
    expect(interpret(p).status).toBe("no_match");
  });
  test("a renamed vintage (e.g. 2028 layers) still resolves by suffix", async () => {
    const p = await fx("legislative-hall");
    const g = p.result.addressMatches[0].geographies;
    g["2028 State Legislative Districts - Upper"] = g["2026 State Legislative Districts - Upper"];
    g["2028 State Legislative Districts - Lower"] = g["2026 State Legislative Districts - Lower"];
    delete g["2026 State Legislative Districts - Upper"];
    delete g["2026 State Legislative Districts - Lower"];
    expect(interpret(p)).toMatchObject({ status: "ok", senate_district: 17, house_district: 32 });
  });
});

describe("countyDistrict", () => {
  const sq = (x0, y0, x1, y1) => ({ type: "Polygon", coordinates: [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]] });
  const geo = { features: [
    { properties: { county: "Kent", district: 1 }, geometry: sq(-75.6, 39.0, -75.5, 39.1) },
    { properties: { county: "Kent", district: 2 }, geometry: sq(-75.5, 39.0, -75.4, 39.1) },
    { properties: { county: "Kent", district: 9 }, geometry: null },
    { properties: { county: "Kent", district: 8 }, geometry: { type: "GeometryCollection", geometries: [] } },
  ] };
  test("clearly inside one district", () => {
    expect(countyDistrict("Kent", -75.55, 39.05, geo)).toEqual({ district: 1, near_line: false });
  });
  test("within 30 m of the shared line is near_line, not a guess", () => {
    expect(countyDistrict("Kent", -75.5001, 39.05, geo)).toEqual({ district: null, near_line: true });
  });
  test("outside every polygon is unknown", () => {
    expect(countyDistrict("Kent", -75.0, 38.0, geo)).toEqual({ district: null, near_line: false });
  });
  test("bundled FirstMap data: Legislative Hall is Kent district 2", () => {
    expect(countyDistrict("Kent", -75.52488, 39.15703).district).toBe(2);
  });
});

describe("ZIP lookups", () => {
  test("19810 lists every overlapping district", () => {
    expect(zipLookup("19810")).toEqual({ status: "zip", zip: "19810", senate_districts: [1, 4, 5], house_districts: [7, 10] });
  });
  test("non-Delaware ZIP", () => {
    expect(zipLookup("10001").status).toBe("not_delaware");
  });
  test("cleanInput accepts spaced ZIPs and addresses, rejects junk", () => {
    expect(cleanInput({ zip: "19 810" })).toEqual({ zip: "19810" });
    expect(cleanInput({ zip: "1981" })).toBeNull();
    expect(cleanInput({ address: "  411   Legislative Ave,  Dover DE " })).toEqual({ address: "411 Legislative Ave, Dover DE" });
    expect(cleanInput({ address: "Main Street Dover" })).toBeNull();
    expect(cleanInput({ address: "1 " + "a".repeat(250) })).toBeNull();
    expect(cleanInput({ address: 19901 })).toBeNull();
    expect(cleanInput(null)).toBeNull();
  });
});

const req = (method, body, { origin = "https://firststatelens.com", type = "application/json", site = "same-origin", ip = "203.0.113." + Math.floor(Math.random() * 250) } = {}) => {
  const text = body === undefined ? undefined : typeof body === "string" ? body : JSON.stringify(body);
  const headers = { "cf-connecting-ip": ip };
  if (origin) headers.origin = origin;
  if (type) headers["content-type"] = type;
  if (site) headers["sec-fetch-site"] = site;
  if (text !== undefined) headers["content-length"] = String(new TextEncoder().encode(text).length);
  return new Request("https://firststatelens.com/api/districts", { method, headers, body: text });
};

describe("request handling", () => {
  const okFetch = async () => new Response(JSON.stringify(await fx("legislative-hall")), { status: 200 });
  const addr = { address: "411 Legislative Ave, Dover, DE 19901" };
  test("POST from our origin returns districts, never cached", async () => {
    const res = await _districtsForTest(req("POST", addr), okFetch);
    expect(res.status).toBe(200);
    expect(res.headers.get("cache-control")).toBe("no-store");
    expect((await res.json()).senate_district).toBe(17);
  });
  test("the address goes to the geocoder only", async () => {
    let seen = "";
    await _districtsForTest(req("POST", addr), async (u) => { seen = u; return okFetch(); });
    expect(seen.startsWith("https://geocoding.geo.census.gov/geocoder/geographies/onelineaddress?")).toBe(true);
    expect(seen).toContain("layers=56%2C58%2C82");
  });
  test("ZIP lookups never call the geocoder", async () => {
    let called = false;
    const res = await _districtsForTest(req("POST", { zip: "19810" }), async () => { called = true; return okFetch(); });
    expect(called).toBe(false);
    expect((await res.json()).house_districts).toEqual([7, 10]);
  });
  test("GET is 405 with Allow", async () => {
    const res = await _districtsForTest(req("GET"), okFetch);
    expect(res.status).toBe(405);
    expect(res.headers.get("allow")).toBe("POST");
  });
  test("missing or foreign origin, or cross-site fetch, is refused", async () => {
    expect((await _districtsForTest(req("POST", addr, { origin: null }), okFetch)).status).toBe(403);
    expect((await _districtsForTest(req("POST", addr, { origin: "https://evil.example" }), okFetch)).status).toBe(403);
    expect((await _districtsForTest(req("POST", addr, { site: "cross-site" }), okFetch)).status).toBe(403);
  });
  test("wrong content type is 415; oversized body is 413", async () => {
    expect((await _districtsForTest(req("POST", addr, { type: "text/plain" }), okFetch)).status).toBe(415);
    expect((await _districtsForTest(req("POST", { ...addr, junk: "x".repeat(5000) }), okFetch)).status).toBe(413);
  });
  test("bad JSON and bad addresses are 400", async () => {
    expect((await _districtsForTest(req("POST", "{not json"), okFetch)).status).toBe(400);
    expect((await _districtsForTest(req("POST", { address: "Dover" }), okFetch)).status).toBe(400);
  });
  test("geocoder outage is a clear 503", async () => {
    const res = await _districtsForTest(req("POST", addr), async () => { throw new Error("down"); });
    expect(res.status).toBe(503);
    expect((await res.json()).status).toBe("unavailable");
  });
  test("burst from one IP is throttled", () => {
    const t0 = 1_000_000;
    let last = false;
    for (let i = 0; i < 13; i++) last = _throttledForTest("198.51.100.7", t0 + i);
    expect(last).toBe(true);
    expect(_throttledForTest("198.51.100.7", t0 + 61_000)).toBe(false);
  });
  test("non-api paths go to static assets; unknown api paths 404", async () => {
    const env = { ASSETS: { fetch: async () => new Response("asset") } };
    expect(await (await worker.fetch(new Request("https://firststatelens.com/vote/"), env)).text()).toBe("asset");
    expect((await worker.fetch(new Request("https://firststatelens.com/api/nope"), env)).status).toBe(404);
  });
});

test("the worker never writes to the console", async () => {
  const src = await Bun.file(new URL("./index.js", import.meta.url)).text();
  expect(/console\.(log|info|warn|error|debug)/.test(src)).toBe(false);
});

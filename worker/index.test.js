// bun test worker/
import { describe, expect, test } from "bun:test";
import worker, { interpret, cleanAddress, _districtsForTest } from "./index.js";

const fx = (n) => Bun.file(new URL(`./fixtures/${n}.json`, import.meta.url)).json();

describe("interpret (Census payload -> our answer)", () => {
  test("Legislative Hall, Dover", async () => {
    const r = interpret(await fx("legislative-hall"));
    expect(r).toMatchObject({ status: "ok", senate_district: 17, house_district: 32, county: "Kent" });
    expect(r.matched_address).toContain("LEGISLATIVE AVE");
    expect(typeof r.lon).toBe("number");
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
});

describe("cleanAddress", () => {
  test("accepts a normal address and collapses whitespace", () => {
    expect(cleanAddress({ address: "  411   Legislative Ave,  Dover DE " })).toBe("411 Legislative Ave, Dover DE");
  });
  test("rejects empty, too long, no number, wrong type", () => {
    expect(cleanAddress({ address: "" })).toBeNull();
    expect(cleanAddress({ address: "Main Street Dover" })).toBeNull();
    expect(cleanAddress({ address: "1 " + "a".repeat(250) })).toBeNull();
    expect(cleanAddress({ address: 19901 })).toBeNull();
    expect(cleanAddress(null)).toBeNull();
  });
});

const req = (method, body, origin = "https://firststatelens.com") =>
  new Request("https://firststatelens.com/api/districts", {
    method,
    headers: { "content-type": "application/json", ...(origin ? { origin } : {}) },
    body: body === undefined ? undefined : typeof body === "string" ? body : JSON.stringify(body),
  });

describe("request handling", () => {
  const okFetch = async () => new Response(JSON.stringify(await fx("legislative-hall")), { status: 200 });
  test("POST from our origin returns districts, never cached", async () => {
    const res = await _districtsForTest(req("POST", { address: "411 Legislative Ave, Dover, DE 19901" }), okFetch);
    expect(res.status).toBe(200);
    expect(res.headers.get("cache-control")).toBe("no-store");
    expect((await res.json()).senate_district).toBe(17);
  });
  test("the address goes to the geocoder in the query, and only there", async () => {
    let seen = "";
    await _districtsForTest(req("POST", { address: "411 Legislative Ave, Dover, DE 19901" }), async (u) => { seen = u; return okFetch(); });
    expect(seen.startsWith("https://geocoding.geo.census.gov/geocoder/geographies/onelineaddress?")).toBe(true);
    expect(seen).toContain("layers=56%2C58%2C82");
  });
  test("GET is refused", async () => {
    expect((await _districtsForTest(req("GET"), okFetch)).status).toBe(405);
  });
  test("another site's origin is refused", async () => {
    expect((await _districtsForTest(req("POST", { address: "1 Main St Dover" }, "https://evil.example"), okFetch)).status).toBe(403);
  });
  test("bad JSON and bad addresses are 400", async () => {
    expect((await _districtsForTest(req("POST", "{not json"), okFetch)).status).toBe(400);
    expect((await _districtsForTest(req("POST", { address: "Dover" }), okFetch)).status).toBe(400);
  });
  test("geocoder outage is a clear 503", async () => {
    const res = await _districtsForTest(req("POST", { address: "411 Legislative Ave, Dover" }), async () => { throw new Error("down"); });
    expect(res.status).toBe(503);
    expect((await res.json()).status).toBe("unavailable");
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

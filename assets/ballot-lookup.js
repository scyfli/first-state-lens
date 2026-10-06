/*
 * First State Lens: "Your 2026 ballot" lookup (docs/UPGRADE-PLAN.md, E2).
 * Sends the typed address to /api/districts (our Worker, which asks the U.S. Census
 * geocoder and stores nothing), then lists every race on that voter's ballot from
 * /candidates/data/ballot-2026.json. County council / levy court district comes from
 * Delaware FirstMap boundaries in /candidates/data/county-districts.geojson.
 * All text is written with textContent; nothing from the network is parsed as HTML.
 */
(function () {
  "use strict";
  var form = document.getElementById("ballot-lookup");
  if (!form) return;
  var input = document.getElementById("ballot-address");
  var out = document.getElementById("ballot-result");
  var button = form.querySelector("button");
  var cache = {};

  function getJSON(url) {
    if (!cache[url]) cache[url] = fetch(url, { cache: "no-cache" }).then(function (r) { if (!r.ok) throw new Error(url); return r.json(); });
    return cache[url];
  }

  function el(tag, attrs, text) {
    var n = document.createElement(tag);
    if (attrs) for (var k in attrs) n.setAttribute(k, attrs[k]);
    if (text != null) n.textContent = text;
    return n;
  }

  function inRing(x, y, ring) {
    var inside = false;
    for (var i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      var xi = ring[i][0], yi = ring[i][1], xj = ring[j][0], yj = ring[j][1];
      if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
    }
    return inside;
  }
  function inGeom(x, y, g) {
    var polys = g.type === "Polygon" ? [g.coordinates] : g.coordinates;
    return polys.some(function (p) {
      return inRing(x, y, p[0]) && !p.slice(1).some(function (h) { return inRing(x, y, h); });
    });
  }
  function countyDistrict(geo, county, lon, lat) {
    if (lon == null || lat == null) return null;
    for (var i = 0; i < geo.features.length; i++) {
      var f = geo.features[i];
      if (f.properties.county === county && inGeom(lon, lat, f.geometry)) return f.properties.district;
    }
    return null;
  }

  function count(n) { return n + " qualified candidate" + (n === 1 ? "" : "s"); }

  function item(list, label, href, detail) {
    var li = el("li");
    var a = el("a", { href: href }, label);
    li.appendChild(a);
    if (detail) li.appendChild(el("span", { "class": "bl-detail" }, " · " + detail));
    list.appendChild(li);
  }

  function message(text, kind) {
    out.textContent = "";
    out.appendChild(el("p", { "class": "bl-msg" + (kind ? " bl-" + kind : "") }, text));
    out.hidden = false;
  }

  function render(d, ballot, geo) {
    var byId = {};
    ballot.races.forEach(function (r) { byId[r.id] = r; });
    var offSenate = {};
    (ballot.senate_not_on_2026_ballot || []).forEach(function (r) { offSenate[r.district] = r; });

    out.textContent = "";
    var head = el("p", { "class": "bl-matched" });
    head.appendChild(el("strong", null, "Matched address: "));
    head.appendChild(document.createTextNode(d.matched_address + ". "));
    head.appendChild(document.createTextNode("State Senate District " + d.senate_district + ", State House District " + d.house_district + ", " + d.county + " County."));
    out.appendChild(head);

    var list = el("ul", { "class": "bl-list" });
    [["us-senate", "U.S. Senate"], ["us-house", "U.S. House, At-Large"], ["attorney-general", "Attorney General"], ["state-treasurer", "State Treasurer"], ["auditor", "Auditor of Accounts"]].forEach(function (p) {
      var r = byId[p[0]];
      if (r) item(list, p[1], r.path, count(r.qualified_count));
    });
    var sen = byId["state-senate-" + d.senate_district];
    if (sen) item(list, "State Senate District " + d.senate_district, sen.path, count(sen.qualified_count));
    else if (offSenate[d.senate_district]) item(list, "State Senate District " + d.senate_district, offSenate[d.senate_district].path, "not on the 2026 ballot (next election 2028)");
    var house = byId["state-house-" + d.house_district];
    if (house) item(list, "State House District " + d.house_district, house.path, count(house.qualified_count));

    var cd = countyDistrict(geo, d.county, d.lon, d.lat);
    var councilShown = false;
    ballot.races.forEach(function (r) {
      if (r.level !== "county" || r.county !== d.county) return;
      if (r.district == null) item(list, r.display, r.path, count(r.qualified_count));
      else if (cd != null && r.district === cd) { item(list, r.display, r.path, count(r.qualified_count)); councilShown = true; }
    });
    out.appendChild(list);

    var noteText;
    if (cd == null) noteText = "We couldn't place this address in a " + d.county + " County council or levy court district. Check your county races on the county page.";
    else if (!councilShown) noteText = "Your " + d.county + " County district (" + cd + ") is not on the 2026 ballot.";
    if (noteText) out.appendChild(el("p", { "class": "bl-msg" }, noteText));

    var confirm = el("p", { "class": "bl-msg" });
    confirm.appendChild(document.createTextNode("Confirm your districts and find your polling place at "));
    confirm.appendChild(el("a", { href: "https://ivote.de.gov" }, "ivote.de.gov"));
    confirm.appendChild(document.createTextNode(". Districts come from the U.S. Census Bureau geocoder and Delaware FirstMap boundaries."));
    out.appendChild(confirm);
    out.hidden = false;
    out.focus();
  }

  form.addEventListener("submit", function (ev) {
    ev.preventDefault();
    var address = (input.value || "").trim();
    if (/^\d{5}(-\d{4})?$/.test(address)) {
      message("A ZIP code alone isn't enough, because Delaware ZIP codes cross district lines. Enter your street address, for example 411 Legislative Ave, Dover, DE.", "warn");
      return;
    }
    button.disabled = true;
    message("Looking up your districts...");
    Promise.all([
      fetch("/api/districts", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ address: address }) })
        .then(function (r) { return r.json().catch(function () { return { status: "unavailable", message: "The lookup isn't responding right now. Try again, or use ivote.de.gov." }; }); }),
      getJSON("/candidates/data/ballot-2026.json"),
      getJSON("/candidates/data/county-districts.geojson"),
    ]).then(function (res) {
      var d = res[0];
      if (!d || d.status !== "ok") { message((d && d.message) || "We couldn't look up that address. Try ivote.de.gov.", "warn"); return; }
      render(d, res[1], res[2]);
    }).catch(function () {
      message("Something went wrong loading the ballot. Try again, or use ivote.de.gov.", "warn");
    }).then(function () { button.disabled = false; });
  });
})();

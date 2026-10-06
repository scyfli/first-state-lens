/*
 * First State Lens: "Your 2026 ballot" lookup (docs/UPGRADE-PLAN.md, E2).
 * Sends the typed street address (or ZIP) to /api/districts, our Worker, which stores and
 * logs nothing. Street addresses are resolved by the U.S. Census geocoder; ZIP codes by a
 * bundled table. The page then lists every race on that ballot from
 * /candidates/data/ballot-2026.json. All text goes in through textContent.
 */
(function () {
  "use strict";
  var form = document.getElementById("ballot-lookup");
  if (!form) return;
  var input = document.getElementById("ballot-address");
  var status = document.getElementById("ballot-status");
  var out = document.getElementById("ballot-result");
  var button = form.querySelector("button");
  var cache = {};
  var IVOTE = "https://ivote.de.gov";
  var MAPS = "https://elections.delaware.gov/maps/";
  var STATEWIDE = [["us-senate", "U.S. Senate"], ["us-house", "U.S. House, At-Large"], ["attorney-general", "Attorney General"], ["state-treasurer", "State Treasurer"], ["auditor", "Auditor of Accounts"]];

  function getJSON(url) {
    if (!cache[url]) {
      cache[url] = fetch(url, { cache: "no-cache" })
        .then(function (r) { if (!r.ok) throw new Error(url); return r.json(); })
        .catch(function (err) { delete cache[url]; throw err; });
    }
    return cache[url];
  }

  function el(tag, attrs, text) {
    var n = document.createElement(tag);
    if (attrs) for (var k in attrs) n.setAttribute(k, attrs[k]);
    if (text != null) n.textContent = text;
    return n;
  }

  function safePath(p) { return typeof p === "string" && p.charAt(0) === "/" && p.charAt(1) !== "/" ? p : "/candidates/"; }
  function count(n) { return n + " qualified candidate" + (n === 1 ? "" : "s"); }

  function item(list, label, href, detail) {
    var li = el("li");
    li.appendChild(el("a", { href: safePath(href) }, label));
    if (detail) li.appendChild(el("span", { "class": "bl-detail" }, " · " + detail));
    list.appendChild(li);
  }

  function linksLine(lead) {
    var p = el("p", { "class": "bl-msg" });
    p.appendChild(document.createTextNode(lead + " Look up your districts at "));
    p.appendChild(el("a", { href: IVOTE }, "ivote.de.gov"));
    p.appendChild(document.createTextNode(" or on the state's "));
    p.appendChild(el("a", { href: MAPS }, "district maps"));
    p.appendChild(document.createTextNode("."));
    return p;
  }

  function setStatus(text, isError) {
    status.textContent = text || "";
    status.className = "bl-status" + (isError ? " bl-warn" : "");
    if (isError) { input.setAttribute("aria-invalid", "true"); input.setAttribute("aria-describedby", "ballot-status ballot-privacy"); }
    else { input.removeAttribute("aria-invalid"); input.setAttribute("aria-describedby", "ballot-privacy"); }
  }

  function fail(text) {
    setStatus(text, true);
    out.textContent = "";
    out.appendChild(linksLine(""));
    out.hidden = false;
  }

  function begin(heading) {
    out.textContent = "";
    var h = el("h3", { "class": "bl-heading", tabindex: "-1", id: "ballot-result-heading" }, heading);
    out.appendChild(h);
    return h;
  }

  function renderAddress(d, ballot) {
    var byId = {}, offSenate = {};
    ballot.races.forEach(function (r) { byId[r.id] = r; });
    (ballot.senate_not_on_2026_ballot || []).forEach(function (r) { offSenate[r.district] = r; });
    var h = begin("Your 2026 ballot");
    var head = el("p", { "class": "bl-matched" });
    head.appendChild(el("strong", null, "Matched address: "));
    head.appendChild(document.createTextNode(d.matched_address + ". State Senate District " + d.senate_district + ", State House District " + d.house_district + ", " + d.county + " County."));
    out.appendChild(head);
    var list = el("ul", { "class": "bl-list" });
    STATEWIDE.forEach(function (p) { var r = byId[p[0]]; if (r) item(list, p[1], r.path, count(r.qualified_count)); });
    var sen = byId["state-senate-" + d.senate_district];
    if (sen) item(list, "State Senate District " + d.senate_district, sen.path, count(sen.qualified_count));
    else if (offSenate[d.senate_district]) item(list, "State Senate District " + d.senate_district, offSenate[d.senate_district].path, "not on the 2026 ballot (next election 2028)");
    var house = byId["state-house-" + d.house_district];
    if (house) item(list, "State House District " + d.house_district, house.path, count(house.qualified_count));
    var councilShown = false;
    ballot.races.forEach(function (r) {
      if (r.level !== "county" || r.county !== d.county) return;
      if (r.district == null) item(list, r.display, r.path, count(r.qualified_count));
      else if (d.county_district != null && r.district === d.county_district) { item(list, r.display, r.path, count(r.qualified_count)); councilShown = true; }
    });
    out.appendChild(list);
    var countyPage = "/candidates/" + d.county.toLowerCase().replace(/ /g, "-") + "-county/";
    if (d.near_county_line) {
      var p = el("p", { "class": "bl-msg bl-warn" }, "This address is close to a " + d.county + " County council or levy court district line, so we don't name one. See every ");
      p.appendChild(el("a", { href: safePath(countyPage) }, d.county + " County race"));
      p.appendChild(document.createTextNode(" and confirm your district at ivote.de.gov."));
      out.appendChild(p);
    } else if (d.county_district == null) {
      var q = el("p", { "class": "bl-msg" }, "We couldn't place this address in a " + d.county + " County council or levy court district. See every ");
      q.appendChild(el("a", { href: safePath(countyPage) }, d.county + " County race"));
      q.appendChild(document.createTextNode("."));
      out.appendChild(q);
    } else if (!councilShown) {
      out.appendChild(el("p", { "class": "bl-msg" }, "Your " + d.county + " County district (" + d.county_district + ") is not on the 2026 ballot."));
    }
    out.appendChild(linksLine("Confirm your districts and find your polling place before you vote."));
    out.hidden = false;
    setStatus("Found your ballot: " + list.children.length + " races.");
    h.focus();
  }

  function renderZip(d, ballot) {
    var byId = {}, offSenate = {};
    ballot.races.forEach(function (r) { byId[r.id] = r; });
    (ballot.senate_not_on_2026_ballot || []).forEach(function (r) { offSenate[r.district] = r; });
    var h = begin("Districts in ZIP code " + d.zip);
    out.appendChild(el("p", { "class": "bl-matched" }, "ZIP codes cross district lines, so ZIP " + d.zip + " touches more than one ballot. Enter your street address above for your exact races. Every voter in Delaware has these statewide races:"));
    var list = el("ul", { "class": "bl-list" });
    STATEWIDE.forEach(function (p) { var r = byId[p[0]]; if (r) item(list, p[1], r.path, count(r.qualified_count)); });
    out.appendChild(list);
    out.appendChild(el("p", { "class": "bl-matched" }, "State legislative districts that overlap this ZIP code:"));
    var leg = el("ul", { "class": "bl-list" });
    d.senate_districts.forEach(function (n) {
      var r = byId["state-senate-" + n];
      if (r) item(leg, "State Senate District " + n, r.path, count(r.qualified_count));
      else if (offSenate[n]) item(leg, "State Senate District " + n, offSenate[n].path, "not on the 2026 ballot");
    });
    d.house_districts.forEach(function (n) { var r = byId["state-house-" + n]; if (r) item(leg, "State House District " + n, r.path, count(r.qualified_count)); });
    out.appendChild(leg);
    out.appendChild(el("p", { "class": "bl-msg" }, "Overlap is from U.S. Census ZIP Code Tabulation Areas and Delaware FirstMap district boundaries; small slivers under 1% of the ZIP area are left out."));
    out.appendChild(linksLine(""));
    out.hidden = false;
    setStatus("ZIP " + d.zip + " overlaps " + d.senate_districts.length + " Senate and " + d.house_districts.length + " House districts.");
    h.focus();
  }

  form.addEventListener("submit", function (ev) {
    ev.preventDefault();
    var raw = (input.value || "").trim();
    var zip = raw.replace(/[\s-]/g, "");
    var payload = /^\d{5}(\d{4})?$/.test(zip) ? { zip: zip.slice(0, 5) } : { address: raw };
    button.disabled = true;
    setStatus("Looking up your districts...");
    var ctrl = typeof AbortController === "function" ? new AbortController() : null;
    var timer = ctrl ? setTimeout(function () { ctrl.abort(); }, 15000) : null;
    Promise.all([
      fetch("/api/districts", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(payload), signal: ctrl ? ctrl.signal : undefined })
        .then(function (r) { return r.json().catch(function () { return { status: "unavailable" }; }); }),
      getJSON("/candidates/data/ballot-2026.json"),
    ]).then(function (res) {
      var d = res[0];
      if (d && d.status === "ok") renderAddress(d, res[1]);
      else if (d && d.status === "zip") renderZip(d, res[1]);
      else fail((d && d.message) || "We couldn't look up that address right now.");
    }).catch(function () {
      fail("The lookup isn't responding right now. Try again in a moment.");
    }).then(function () { if (timer) clearTimeout(timer); button.disabled = false; });
  });

  button.disabled = false; // enabled only once this handler is attached
})();

/*
 * First State Lens: "My Delaware" by address (docs/UPGRADE-PLAN.md, Y4).
 * Sends the typed address (or ZIP) to /api/districts, our Worker, which stores and logs
 * nothing, then fills in legislators, county seat, school district and the 2026 ballot from
 * the page's own data block (#md-data, built by etl/pages/my_delaware_page.py).
 * All text goes in through textContent; links only to same-site paths from the data block.
 */
(function () {
  "use strict";
  var form = document.getElementById("md-form");
  var dataEl = document.getElementById("md-data");
  if (!form || !dataEl) return;
  var D = JSON.parse(dataEl.textContent);
  var input = document.getElementById("md-address");
  var status = document.getElementById("md-status");
  var out = document.getElementById("md-result");
  var button = form.querySelector("button");
  var IVOTE = "https://ivote.de.gov";

  function el(tag, attrs, text) {
    var n = document.createElement(tag);
    if (attrs) for (var k in attrs) n.setAttribute(k, attrs[k]);
    if (text != null) n.textContent = text;
    return n;
  }
  function safe(p) { return typeof p === "string" && p.charAt(0) === "/" && p.charAt(1) !== "/" ? p : "/"; }
  function link(href, text) { return el("a", { href: safe(href) }, text); }
  function heading(text) { return el("h3", { tabindex: "-1" }, text); }
  function msg(parts) {
    var p = el("p", { "class": "md-msg" });
    parts.forEach(function (x) { p.appendChild(typeof x === "string" ? document.createTextNode(x) : x); });
    return p;
  }
  function li(list, parts) {
    var item = el("li");
    parts.forEach(function (x) { item.appendChild(typeof x === "string" ? document.createTextNode(x) : x); });
    list.appendChild(item);
  }
  function who(h) {
    if (!h || !h.name) return "Holder not listed in the Office Registry.";
    return h.name + (h.party ? " (" + h.party + ")" : "");
  }

  function renderAddress(d) {
    out.textContent = "";
    var first = heading("Your legislators");
    out.appendChild(first);
    out.appendChild(msg(["Matched address: ", el("strong", null, d.matched_address || "")]));
    var s = D.senate[d.senate_district], h = D.house[d.house_district];
    var leg = el("ul", { "class": "md-list" });
    li(leg, ["State Senate District " + d.senate_district + ": " + who(s) + ". ", link("/offices/general-assembly/", "Office Registry"), " · ", link("/votes/", "Voting record")]);
    li(leg, ["State House District " + d.house_district + ": " + who(h) + ". ", link("/offices/general-assembly/", "Office Registry"), " · ", link("/votes/", "Voting record")]);
    out.appendChild(leg);

    out.appendChild(heading(d.county + " County"));
    var cty = D.counties[d.county] || {};
    var seats = D.council[d.county] || {};
    var body = (seats[Object.keys(seats)[0]] || {}).body || "council";
    var cl = el("ul", { "class": "md-list" });
    if (d.near_county_line) {
      li(cl, [el("span", { "class": "md-warn" }, "This address is close to a " + body + " district line, so we do not name a district. "), "Check the county's own map."]);
    } else if (d.county_district != null && seats[d.county_district]) {
      li(cl, [body + " District " + d.county_district + ": " + who(seats[d.county_district]) + "."]);
    } else {
      li(cl, ["We could not place this address in a " + body + " district."]);
    }
    li(cl, [link(cty.offices, "Every " + d.county + " County office and who holds it")]);
    out.appendChild(cl);

    out.appendChild(heading("Your school district"));
    var sp = d.school_district ? D.schools[d.school_district] : null;
    if (sp) out.appendChild(msg([link(sp, d.school_district + " report card"), ". Charter, vocational-technical and choice schools serve students across district lines; see ", link("/schools/", "every report card"), "."]));
    else out.appendChild(msg(["The geocoder did not return a public school district for this address. See ", link("/schools/", "every district's report card"), "."]));

    out.appendChild(heading("Your 2026 ballot"));
    var bl = el("ul", { "class": "md-list" });
    D.statewide.forEach(function (r) { li(bl, [link(r[1], r[0])]); });
    li(bl, [link(s.path, "State Senate District " + d.senate_district), s.on_ballot ? "" : " (not on the 2026 ballot)"]);
    li(bl, [link(h.path, "State House District " + d.house_district)]);
    li(bl, [link(cty.ballot, d.county + " County races")]);
    out.appendChild(bl);

    out.appendChild(heading("Water and child care"));
    out.appendChild(msg(["We cannot match an address to a water system yet. Find yours by name or town on the ", link("/water/", "drinking water page"), ". For child care, see ", link("/childcare/", "licensed providers by county"), "."]));
    out.appendChild(msg(["Confirm your districts and polling place at ", el("a", { href: IVOTE }, "ivote.de.gov"), "."]));
    out.hidden = false;
    first.focus();
  }

  function renderZip(d) {
    out.textContent = "";
    var first = heading("ZIP " + d.zip + " overlaps these districts");
    out.appendChild(first);
    var l = el("ul", { "class": "md-list" });
    (d.senate_districts || []).forEach(function (n) { var s = D.senate[n]; if (s) li(l, ["State Senate District " + n + ": " + who(s) + ". ", link(s.path, "Ballot page")]); });
    (d.house_districts || []).forEach(function (n) { var h = D.house[n]; if (h) li(l, ["State House District " + n + ": " + who(h) + ". ", link(h.path, "Ballot page")]); });
    out.appendChild(l);
    out.appendChild(msg(["A ZIP code can cross district lines. Enter your street address to narrow it to your own districts, county seat and school district."]));
    out.hidden = false;
    first.focus();
  }

  button.disabled = false;
  form.addEventListener("submit", function (ev) {
    ev.preventDefault();
    var raw = (input.value || "").trim();
    if (!raw) return;
    var zip = raw.replace(/\s|-/g, "");
    var payload = /^\d{5}(\d{4})?$/.test(zip) ? { zip: zip.slice(0, 5) } : { address: raw };
    button.disabled = true;
    status.textContent = "Looking up your districts…";
    fetch("/api/districts", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(payload) })
      .then(function (r) { return r.json().catch(function () { return null; }); })
      .then(function (d) {
        if (d && d.status === "ok") { status.textContent = ""; renderAddress(d); }
        else if (d && d.status === "zip") { status.textContent = ""; renderZip(d); }
        else { out.hidden = true; status.textContent = (d && d.message) || "We couldn't look that up right now. Try again, or check ivote.de.gov."; }
      })
      .catch(function () { out.hidden = true; status.textContent = "We couldn't reach the lookup. Check your districts at ivote.de.gov."; })
      .then(function () { button.disabled = false; });
  });
})();

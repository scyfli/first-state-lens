/*
 * First State Lens: 2026 general election deadline banner.
 *
 * One schedule, used by every page that carries a [data-election-banner]
 * element and by the "next deadline" block on /vote/. Every date and hour
 * comes from the Delaware Department of Elections 2026 Election Calendar:
 * https://elections.delaware.gov/public/calendar/pdfs/2026ElectionCalendar.pdf
 *
 * The page's static HTML carries a fallback message for readers without
 * JavaScript; this script replaces it with the message for the current
 * Delaware (America/New_York) date and hour, and hides the banner after
 * certification.
 */
(function (root) {
  "use strict";

  var SOURCE = "https://elections.delaware.gov/public/calendar/pdfs/2026ElectionCalendar.pdf";

  // Early voting days and hours (open hour, close hour, 24h clock).
  var EARLY = {
    "2026-10-22": [7, 19], "2026-10-23": [7, 19], "2026-10-24": [7, 19],
    "2026-10-26": [7, 19], "2026-10-27": [7, 19],
    "2026-10-28": [11, 19], "2026-10-29": [11, 19], "2026-10-30": [11, 19],
    "2026-10-31": [11, 19], "2026-11-01": [11, 19]
  };
  var EARLY_DAYS = Object.keys(EARLY).sort();

  function hourLabel(h) {
    if (h === 12) return "noon";
    return (h > 12 ? h - 12 : h) + (h >= 12 ? " p.m." : " a.m.");
  }

  function weekdayLong(iso) {
    var p = iso.split("-").map(Number);
    var d = new Date(Date.UTC(p[0], p[1] - 1, p[2], 12));
    var days = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
    var months = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
    return days[d.getUTCDay()] + ", " + months[d.getUTCMonth()] + " " + d.getUTCDate();
  }

  function nextEarlyDay(iso) {
    for (var i = 0; i < EARLY_DAYS.length; i++) if (EARLY_DAYS[i] > iso) return EARLY_DAYS[i];
    return null;
  }

  /*
   * Pure function: given a Delaware-local date (YYYY-MM-DD) and hour (0-23),
   * return { text, href } for the banner, or null when no banner should show.
   */
  function bannerFor(iso, hour) {
    if (iso <= "2026-10-10") {
      return { text: "Voter registration for the November 3 general election closes Saturday, October 10, at 11:59 p.m.", href: "/vote/#register" };
    }
    if (iso < "2026-10-22") {
      var lead = iso <= "2026-10-19" ? "Uniformed service members and citizens living abroad can still register through Monday, October 19. " : "";
      return { text: lead + "Early voting opens Thursday, October 22, at 7 a.m.", href: "/vote/#early" };
    }
    if (iso <= "2026-11-01") {
      var hrs = EARLY[iso];
      if (hrs && hour < hrs[0]) {
        return { text: "Early voting is open today from " + hourLabel(hrs[0]) + " to " + hourLabel(hrs[1]) + ", at any early voting site in your county.", href: "/vote/#early" };
      }
      if (hrs && hour < hrs[1]) {
        return { text: "Early voting is open now until " + hourLabel(hrs[1]) + ", at any early voting site in your county.", href: "/vote/#early" };
      }
      var nxt = nextEarlyDay(iso);
      if (nxt) {
        var o = EARLY[nxt][0];
        var when = (iso === "2026-10-25" || !hrs) ? "There is no early voting today. " : "Early voting has closed for today. ";
        var tail = hourLabel(o); return { text: when + "It reopens " + weekdayLong(nxt) + ", at " + tail + (/\.$/.test(tail) ? "" : "."), href: "/vote/#early" };
      }
      return { text: "Early voting has ended. Election Day is Tuesday, November 3. Polls are open 7 a.m. to 8 p.m.", href: "/vote/#election-day" };
    }
    if (iso === "2026-11-02") {
      return { text: "Election Day is tomorrow, Tuesday, November 3. Polls are open 7 a.m. to 8 p.m. at your assigned polling place.", href: "/vote/#election-day" };
    }
    if (iso === "2026-11-03") {
      if (hour < 20) {
        return { text: "Today is Election Day. Polls are open until 8 p.m. Absentee ballots must reach your county elections office by 8 p.m.", href: "/vote/#election-day" };
      }
      return { text: "Polls have closed. Each county's Board of Canvass certifies the results on Thursday, November 5.", href: "/vote/#results" };
    }
    if (iso <= "2026-11-05") {
      return { text: "Each county's Board of Canvass certifies the November 3 results on Thursday, November 5, at 10 a.m.", href: "/vote/#results" };
    }
    return null;
  }

  function delawareNow(date) {
    var parts = new Intl.DateTimeFormat("en-US", {
      timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", hourCycle: "h23"
    }).formatToParts(date || new Date());
    var get = function (t) { for (var i = 0; i < parts.length; i++) if (parts[i].type === t) return parts[i].value; return ""; };
    return { iso: get("year") + "-" + get("month") + "-" + get("day"), hour: Number(get("hour")) % 24 };
  }

  function render(doc) {
    var now = delawareNow();
    var msg = bannerFor(now.iso, now.hour);
    var nodes = doc.querySelectorAll("[data-election-banner]");
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i];
      if (!msg) { el.hidden = true; continue; }
      var textEl = el.querySelector("[data-election-text]");
      var linkEl = el.querySelector("[data-election-link]");
      if (textEl) textEl.textContent = msg.text;
      if (linkEl) {
        if (el.hasAttribute("data-election-onpage")) linkEl.setAttribute("href", msg.href.replace("/vote/", ""));
        else linkEl.setAttribute("href", msg.href);
      }
      el.hidden = false;
    }
  }

  var api = { bannerFor: bannerFor, delawareNow: delawareNow, SOURCE: SOURCE };
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  } else {
    root.FSLElection = api;
    if (root.document) {
      if (root.document.readyState === "loading") root.document.addEventListener("DOMContentLoaded", function () { render(root.document); });
      else render(root.document);
    }
  }
})(typeof window !== "undefined" ? window : this);

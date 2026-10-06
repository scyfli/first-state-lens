// bun test scripts/election-banner.test.ts
// Pins every message the 2026 deadline banner can show against the
// Department of Elections 2026 Election Calendar.
import { describe, expect, test } from "bun:test";
// eslint-disable-next-line @typescript-eslint/no-var-requires
const { bannerFor, delawareNow } = require("../assets/election-banner.js");

const t = (iso: string, hour = 12) => bannerFor(iso, hour)?.text ?? null;

describe("registration window", () => {
  test("today and through the deadline day", () => {
    expect(t("2026-10-05")).toContain("closes Saturday, October 10, at 11:59 p.m.");
    expect(t("2026-10-10", 23)).toContain("October 10");
  });
  test("after the deadline, the overseas window and early voting date", () => {
    expect(t("2026-10-11")).toContain("through Monday, October 19");
    expect(t("2026-10-19")).toContain("October 19");
    expect(t("2026-10-20")).not.toContain("October 19");
    expect(t("2026-10-21")).toBe("Early voting opens Thursday, October 22, at 7 a.m.");
  });
});

describe("early voting", () => {
  test("7 a.m. to 7 p.m. days", () => {
    expect(t("2026-10-22", 6)).toContain("open today from 7 a.m. to 7 p.m.");
    expect(t("2026-10-22", 7)).toContain("open now until 7 p.m.");
    expect(t("2026-10-24", 19)).toContain("reopens Monday, October 26, at 7 a.m.");
  });
  test("Sunday October 25 has no early voting", () => {
    expect(t("2026-10-25", 12)).toBe("There is no early voting today. It reopens Monday, October 26, at 7 a.m.");
  });
  test("11 a.m. to 7 p.m. days", () => {
    expect(t("2026-10-27", 20)).toContain("reopens Wednesday, October 28, at 11 a.m.");
    expect(t("2026-10-28", 9)).toContain("open today from 11 a.m. to 7 p.m.");
    expect(t("2026-11-01", 18)).toContain("open now until 7 p.m.");
  });
  test("after the last early voting day closes", () => {
    expect(t("2026-11-01", 19)).toContain("Early voting has ended. Election Day is Tuesday, November 3.");
  });
});

describe("election day and certification", () => {
  test("day before and the day", () => {
    expect(t("2026-11-02")).toContain("Election Day is tomorrow");
    expect(t("2026-11-03", 7)).toContain("Polls are open until 8 p.m.");
    expect(t("2026-11-03", 20)).toContain("Polls have closed");
  });
  test("certification, then the banner hides", () => {
    expect(t("2026-11-04")).toContain("Thursday, November 5, at 10 a.m.");
    expect(t("2026-11-05")).toContain("November 5");
    expect(t("2026-11-06")).toBeNull();
  });
});

describe("every day from now to certification has a message", () => {
  test("no gaps", () => {
    const d = new Date(Date.UTC(2026, 9, 5, 12));
    while (d.toISOString().slice(0, 10) <= "2026-11-05") {
      const iso = d.toISOString().slice(0, 10);
      for (const h of [0, 6, 7, 10, 11, 18, 19, 20, 23]) expect(bannerFor(iso, h)).not.toBeNull();
      d.setUTCDate(d.getUTCDate() + 1);
    }
  });
});

describe("Delaware clock", () => {
  test("converts UTC to Eastern, across the Nov 1 DST change", () => {
    // 2026-10-23 03:30 UTC is 11:30 p.m. Oct 22 in Delaware (EDT, UTC-4)
    expect(delawareNow(new Date("2026-10-23T03:30:00Z"))).toEqual({ iso: "2026-10-22", hour: 23 });
    // 2026-11-03 12:30 UTC is 7:30 a.m. Nov 3 (EST, UTC-5)
    expect(delawareNow(new Date("2026-11-03T12:30:00Z"))).toEqual({ iso: "2026-11-03", hour: 7 });
  });
});

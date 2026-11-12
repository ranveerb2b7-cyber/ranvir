import { describe, expect, it } from "vitest";

import { describeFilters, formatBytes, REPORT_TYPE_ORDER } from "@/lib/reports";

describe("reports", () => {
  it("offers every report type the API accepts", () => {
    expect([...REPORT_TYPE_ORDER].sort()).toEqual(
      ["alerts", "brand", "errors", "marketplace", "product", "scan_summary", "seller"].sort(),
    );
  });

  it("describes stored filters in plain words", () => {
    expect(describeFilters({ report_type: "product", filters: {} })).toBe("All");
    expect(describeFilters({ report_type: "product", filters: { brand: "__none__", monitoring: true } })).toBe(
      "No brand · Monitored only",
    );
    expect(describeFilters({ report_type: "errors", filters: {} })).toBe("Last 30 days");
    expect(describeFilters({ report_type: "alerts", filters: { date_from: "2026-11-01", status: "open" } })).toBe(
      "2026-11-01 to today · Status: open",
    );
    expect(describeFilters({ report_type: "seller", filters: { tag: "authorized", currently_offering: false } })).toBe(
      "Tag: authorized · Not offering now",
    );
  });

  it("formats sizes and keeps unknown sizes unknown", () => {
    expect(formatBytes(null)).toBeNull();
    expect(formatBytes(900)).toBe("900 B");
    expect(formatBytes(2048)).toBe("2.0 KB");
    expect(formatBytes(3 * 1024 * 1024)).toBe("3.0 MB");
  });
});

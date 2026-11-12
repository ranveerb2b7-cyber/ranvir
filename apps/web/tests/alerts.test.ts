import { describe, expect, it } from "vitest";

import { describeRule, RULE_TYPE_ORDER, RULE_TYPES } from "@/lib/alerts";
import type { AlertRuleType } from "@/lib/types";

// Must match the API's rule types (sellerscope.models.enums.AlertRuleType).
const API_RULE_TYPES: AlertRuleType[] = [
  "new_seller",
  "seller_count_above",
  "price_below",
  "offer_count_change",
  "scan_failed",
  "seller_gone",
  "buy_box_changed",
];

describe("alert rule metadata", () => {
  it("covers every rule type the API accepts", () => {
    expect([...RULE_TYPE_ORDER].sort()).toEqual([...API_RULE_TYPES].sort());
  });

  it("marks threshold fields required", () => {
    for (const type of ["seller_count_above", "price_below"] as const) {
      const threshold = RULE_TYPES[type].fields.find((f) => f.key === "threshold");
      expect(threshold).toMatchObject({ kind: "number", required: true });
    }
  });

  it("describes rules in plain words", () => {
    expect(describeRule({ rule_type: "seller_count_above", params: { threshold: 3 } })).toBe("More than 3 sellers");
    expect(describeRule({ rule_type: "seller_count_above", params: { threshold: 1 } })).toBe("More than 1 seller");
    expect(
      describeRule({ rule_type: "price_below", params: { threshold: "499.00", exclude_seller_tags: ["authorized"] } }),
    ).toBe("Below ₹499.00 · ignoring authorized");
    expect(describeRule({ rule_type: "seller_gone", params: { include_inconclusive: false } })).toBe("Proven only");
    expect(describeRule({ rule_type: "seller_gone", params: { include_inconclusive: true } })).toBe("Including inconclusive");
    expect(describeRule({ rule_type: "offer_count_change", params: { min_change: 2, direction: "decrease" } })).toBe(
      "Offer count decrease of 2 or more",
    );
    expect(describeRule({ rule_type: "new_seller", params: { min_confidence: "high", exclude_seller_tags: [] } })).toBe(
      "Certain new sellers only",
    );
  });
});

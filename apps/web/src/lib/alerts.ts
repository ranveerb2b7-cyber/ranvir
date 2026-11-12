import type { AlertRule, AlertRuleType, AlertSeverity } from "@/lib/types";

/** A rule setting shown in the rule form. Keys match the API's per-type params. */
export type ParamField =
  | { key: string; kind: "number"; label: string; hint?: string; min: number; step?: string; required?: boolean }
  | { key: string; kind: "boolean"; label: string; hint?: string }
  | { key: string; kind: "select"; label: string; options: { value: string; label: string }[] }
  | { key: string; kind: "tags"; label: string; hint?: string };

export interface RuleTypeInfo {
  label: string;
  description: string;
  defaultSeverity: AlertSeverity;
  fields: ParamField[];
}

const EXCLUDE_TAGS = (hint: string): ParamField => ({
  key: "exclude_seller_tags",
  kind: "tags",
  label: "Ignore sellers tagged",
  hint,
});

export const RULE_TYPES: Record<AlertRuleType, RuleTypeInfo> = {
  new_seller: {
    label: "New seller",
    description: "A seller starts offering one of your products.",
    defaultSeverity: "warning",
    fields: [
      {
        key: "min_confidence",
        kind: "select",
        label: "Alert on",
        options: [
          { value: "medium", label: "Every new seller (including ones that may have been hidden in a cut-off list)" },
          { value: "high", label: "Only certain new sellers (previous list was complete)" },
        ],
      },
      EXCLUDE_TAGS("Comma-separated tags from Seller Intelligence, e.g. authorized."),
    ],
  },
  seller_gone: {
    label: "Seller gone",
    description: "A seller stops offering one of your products (proven by a complete offer list).",
    defaultSeverity: "info",
    fields: [
      {
        key: "include_inconclusive",
        kind: "boolean",
        label: "Also alert when a seller is missing from a cut-off list",
        hint: "Inconclusive: the seller may still be selling.",
      },
      EXCLUDE_TAGS("Comma-separated tags, e.g. authorized."),
    ],
  },
  buy_box_changed: {
    label: "Buy Box changed",
    description: "A different seller wins the Buy Box.",
    defaultSeverity: "warning",
    fields: [EXCLUDE_TAGS("No alert when the new winner has one of these tags (e.g. your own seller tag).")],
  },
  offer_count_change: {
    label: "Offer count changed",
    description: "Amazon reports a different total number of offers.",
    defaultSeverity: "info",
    fields: [
      { key: "min_change", kind: "number", label: "Minimum change", min: 1, hint: "Ignore smaller changes." },
      {
        key: "direction",
        kind: "select",
        label: "Direction",
        options: [
          { value: "any", label: "Up or down" },
          { value: "increase", label: "Only increases" },
          { value: "decrease", label: "Only decreases" },
        ],
      },
    ],
  },
  seller_count_above: {
    label: "Too many sellers",
    description: "A product has more sellers than you allow. Resolves itself when the count drops.",
    defaultSeverity: "warning",
    fields: [{ key: "threshold", kind: "number", label: "Alert above this many sellers", min: 0, required: true }],
  },
  price_below: {
    label: "Price below",
    description: "Any offer's price including shipping goes below your price (e.g. MAP). Resolves itself.",
    defaultSeverity: "critical",
    fields: [
      { key: "threshold", kind: "number", label: "Price (₹, including shipping)", min: 0.01, step: "0.01", required: true },
      EXCLUDE_TAGS("Offers from sellers with these tags are not checked."),
    ],
  },
  scan_failed: {
    label: "Scan failed",
    description: "A product couldn't be scanned. Resolves itself on the next successful scan.",
    defaultSeverity: "warning",
    fields: [
      {
        key: "include_unavailable",
        kind: "boolean",
        label: "Also alert when Amazon reports the product unavailable or not found",
      },
    ],
  },
};

export const RULE_TYPE_ORDER = Object.keys(RULE_TYPES) as AlertRuleType[];

export const SEVERITY_LABELS: Record<AlertSeverity, string> = {
  critical: "Critical",
  warning: "Warning",
  info: "Info",
};

/** One-line description of a rule's settings, for the rules table. */
export function describeRule(rule: Pick<AlertRule, "rule_type" | "params">): string {
  const p = rule.params;
  const tags = Array.isArray(p.exclude_seller_tags) && p.exclude_seller_tags.length > 0
    ? ` · ignoring ${(p.exclude_seller_tags as string[]).join(", ")}`
    : "";
  switch (rule.rule_type) {
    case "new_seller":
      return (p.min_confidence === "high" ? "Certain new sellers only" : "Any new seller") + tags;
    case "seller_gone":
      return (p.include_inconclusive ? "Including inconclusive" : "Proven only") + tags;
    case "buy_box_changed":
      return "Any change" + tags;
    case "offer_count_change": {
      const dir = p.direction === "increase" ? "increase" : p.direction === "decrease" ? "decrease" : "change";
      return `Offer count ${dir} of ${String(p.min_change ?? 1)} or more`;
    }
    case "seller_count_above":
      return `More than ${String(p.threshold)} seller${p.threshold === 1 ? "" : "s"}`;
    case "price_below":
      return `Below ₹${String(p.threshold)}` + tags;
    case "scan_failed":
      return p.include_unavailable ? "Failures and unavailable products" : "Failures";
  }
}

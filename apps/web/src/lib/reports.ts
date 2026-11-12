import type { ReportExport, ReportType } from "@/lib/types";

export type FilterKind = "product" | "seller" | "dates" | "alerts" | "none";

export const REPORT_TYPES: Record<ReportType, { label: string; description: string; filters: FilterKind }> = {
  product: {
    label: "Products",
    description: "One row per product: offers, sellers and prices from its latest scan, with notes on any missing data.",
    filters: "product",
  },
  brand: {
    label: "Brands",
    description: "Per brand: products, sellers observed, price range and products with unavailable data.",
    filters: "none",
  },
  seller: {
    label: "Sellers",
    description: "Every seller seen on your products: your labels, products they offer now and Buy Box holds.",
    filters: "seller",
  },
  marketplace: {
    label: "Marketplace summary",
    description: "Totals for Amazon.in: products, scans, sellers and unavailable data.",
    filters: "none",
  },
  scan_summary: {
    label: "Scan summary",
    description: "Every scan job in a period, with its outcome counts.",
    filters: "dates",
  },
  errors: {
    label: "Errors and unavailable",
    description: "Every scan in a period that failed or found no offer data, with the reason.",
    filters: "dates",
  },
  alerts: {
    label: "Alert history",
    description: "Every alert raised in a period, with its status and email delivery.",
    filters: "alerts",
  },
};

export const REPORT_TYPE_ORDER = Object.keys(REPORT_TYPES) as ReportType[];

/** Plain-language summary of a report's stored filters. */
export function describeFilters(report: Pick<ReportExport, "report_type" | "filters">): string {
  const f = report.filters;
  const parts: string[] = [];
  if (typeof f.brand === "string") parts.push(f.brand === "__none__" ? "No brand" : `Brand: ${f.brand}`);
  if (typeof f.monitoring === "boolean") parts.push(f.monitoring ? "Monitored only" : "Not monitored");
  if (typeof f.tag === "string") parts.push(`Tag: ${f.tag}`);
  if (typeof f.currently_offering === "boolean")
    parts.push(f.currently_offering ? "Offering now" : "Not offering now");
  if (typeof f.status === "string") parts.push(`Status: ${f.status}`);
  const kind = REPORT_TYPES[report.report_type].filters;
  if (kind === "dates" || kind === "alerts") {
    const from = typeof f.date_from === "string" ? f.date_from : null;
    const to = typeof f.date_to === "string" ? f.date_to : null;
    parts.unshift(from || to ? `${from ?? "…"} to ${to ?? "today"}` : "Last 30 days");
  }
  return parts.join(" · ") || "All";
}

export function formatBytes(bytes: number | null): string | null {
  if (bytes === null) return null;
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

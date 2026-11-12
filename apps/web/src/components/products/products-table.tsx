"use client";

import clsx from "clsx";
import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react";

import { Value } from "@/components/ui/value";
import { formatCount, formatDateTime, formatPrice } from "@/lib/format";
import { MARKETPLACE_LABELS, SCAN_STATUS_LABELS, type Product, type ScanStatus } from "@/lib/types";

export type SortKey =
  | "created_at"
  | "external_id"
  | "product_name"
  | "brand_name"
  | "last_scanned_at"
  | "total_offer_count"
  | "unique_seller_count"
  | "lowest_observed_price"
  | "highest_observed_price";

const STATUS_STYLE: Record<ScanStatus, string> = {
  not_scanned: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300",
  ok: "bg-green-100 text-green-800 dark:bg-green-950 dark:text-green-300",
  partial: "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300",
  not_found: "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300",
  unavailable: "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300",
  error: "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300",
};

export function StatusBadge({ status }: { status: ScanStatus }) {
  return (
    <span className={clsx("inline-block rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap", STATUS_STYLE[status])}>
      {SCAN_STATUS_LABELS[status]}
    </span>
  );
}

const NOT_SCANNED = "This product has not been scanned yet.";

/** Offer count = marketplace-reported total. When only part of the list was received, say so. */
export function OfferCount({ product }: { product: Product }) {
  const scan = product.latest_scan;
  if (!scan) return <Value why={NOT_SCANNED}>{null}</Value>;
  const total = formatCount(scan.total_offer_count);
  if (total === null) return <Value why="The marketplace did not report an offer count.">{null}</Value>;
  const partial = scan.total_offer_count !== null && scan.observed_offer_count < scan.total_offer_count;
  return (
    <span title={`${scan.observed_offer_count} offer(s) received in detail`}>
      <span className="tabular-nums">{total}</span>
      {partial && <span className="block text-xs text-[var(--text-muted)]">{scan.observed_offer_count} observed</span>}
    </span>
  );
}

export function SellerCount({ product }: { product: Product }) {
  const scan = product.latest_scan;
  if (!scan) return <Value why={NOT_SCANNED}>{null}</Value>;
  return (
    <Value why="Seller identities were not provided by the data source.">
      {formatCount(scan.unique_seller_count)}
    </Value>
  );
}

export function Price({ product, which }: { product: Product; which: "lowest" | "highest" }) {
  const scan = product.latest_scan;
  const value = which === "lowest" ? scan?.lowest_observed_price : scan?.highest_observed_price;
  return (
    <Value why={scan ? "No prices were observed in the latest scan." : NOT_SCANNED}>
      {formatPrice(value, scan?.currency)}
    </Value>
  );
}

interface Column {
  key: string;
  label: string;
  sort?: SortKey;
  numeric?: boolean;
  render: (p: Product) => React.ReactNode;
}

export const COLUMNS: Column[] = [
  { key: "marketplace", label: "Marketplace", render: (p) => MARKETPLACE_LABELS[p.marketplace] ?? p.marketplace },
  {
    key: "asin",
    label: "ASIN",
    sort: "external_id",
    render: (p) => <span className="font-mono text-xs">{p.external_id}</span>,
  },
  {
    key: "name",
    label: "Product name",
    sort: "product_name",
    render: (p) => p.product_name ?? <span className="text-[var(--text-muted)]">—</span>,
  },
  {
    key: "brand",
    label: "Brand",
    sort: "brand_name",
    render: (p) => p.brand_name ?? <span className="text-[var(--text-muted)]">—</span>,
  },
  { key: "offers", label: "Offer count", sort: "total_offer_count", numeric: true, render: (p) => <OfferCount product={p} /> },
  {
    key: "sellers",
    label: "Unique sellers",
    sort: "unique_seller_count",
    numeric: true,
    render: (p) => <SellerCount product={p} />,
  },
  {
    key: "low",
    label: "Lowest price",
    sort: "lowest_observed_price",
    numeric: true,
    render: (p) => <Price product={p} which="lowest" />,
  },
  {
    key: "high",
    label: "Highest price",
    sort: "highest_observed_price",
    numeric: true,
    render: (p) => <Price product={p} which="highest" />,
  },
  {
    key: "scanned",
    label: "Last scanned",
    sort: "last_scanned_at",
    render: (p) => <Value why={NOT_SCANNED}>{formatDateTime(p.last_scanned_at)}</Value>,
  },
  { key: "status", label: "Scan status", render: (p) => <StatusBadge status={p.scan_status} /> },
];

export function SortHeader({ column, sort, order, onSort }: {
  column: Column;
  sort: SortKey;
  order: "asc" | "desc";
  onSort: (key: SortKey) => void;
}) {
  if (!column.sort) return <>{column.label}</>;
  const active = column.sort === sort;
  const Icon = !active ? ArrowUpDown : order === "asc" ? ArrowUp : ArrowDown;
  return (
    <button
      type="button"
      onClick={() => onSort(column.sort!)}
      className={clsx("inline-flex items-center gap-1 hover:text-[var(--text)]", active && "text-[var(--text)]")}
    >
      {column.label}
      <Icon aria-hidden className="size-3" />
    </button>
  );
}

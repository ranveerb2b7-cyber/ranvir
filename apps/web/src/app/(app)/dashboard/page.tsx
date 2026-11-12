"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";

import { useSession } from "@/components/session/session-provider";
import { Alert, errorMessage } from "@/components/ui/form";
import { MetricTile } from "@/components/ui/metric-tile";
import { Value } from "@/components/ui/value";
import { api } from "@/lib/api";
import { formatCount, formatDateTime, reasonText } from "@/lib/format";
import type { DashboardSummary, Metric } from "@/lib/types";

const TILES: { key: keyof DashboardSummary; label: string }[] = [
  { key: "total_products_monitored", label: "Total products monitored" },
  { key: "products_successfully_scanned", label: "Products successfully scanned" },
  { key: "products_with_multiple_sellers", label: "Products with multiple sellers" },
  { key: "total_offers_observed", label: "Total offers observed" },
  { key: "new_sellers_detected_7d", label: "New sellers detected (7 days)" },
  { key: "products_with_unavailable_data", label: "Products with unavailable data" },
  { key: "open_alerts", label: "Open alerts" },
];

function metricCell(m: Metric) {
  return <Value why={reasonText(m.reason)}>{formatCount(m.value)}</Value>;
}

export default function DashboardPage() {
  const { org } = useSession();
  const summary = useQuery({
    queryKey: ["tenant", org.id, "dashboard"],
    queryFn: () => api<DashboardSummary>("/dashboard/summary", { orgId: org.id }),
  });
  const data = summary.data;

  return (
    <section>
      <h1 className="text-2xl font-semibold tracking-tight">Dashboard</h1>
      <p className="mt-1 text-sm text-[var(--text-muted)]">
        Coverage: Amazon.in via the official Selling Partner API. Flipkart is not in the current scope.
        {data?.last_scan_at && <> Last scan: {formatDateTime(data.last_scan_at)}.</>}
      </p>

      {summary.error && (
        <div className="mt-4">
          <Alert>{errorMessage(summary.error)}</Alert>
        </div>
      )}

      <div className="mt-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {TILES.map(({ key, label }) => {
          const metric = data?.[key] as Metric | undefined;
          return (
            <MetricTile
              key={key}
              label={label}
              value={metric?.value ?? null}
              unavailableReason={metric ? reasonText(metric.reason) : "Loading…"}
              note={metric?.value !== null ? reasonText(metric?.reason) : undefined}
            />
          );
        })}
      </div>

      {data && data.total_products_monitored.value === 0 && (
        <p className="mt-4 text-sm text-[var(--text-muted)]">
          No products yet. <Link href="/products" className="text-brand-600 font-medium">Add your first ASIN</Link> to start monitoring.
        </p>
      )}

      <h2 className="mt-8 text-lg font-semibold">Marketplace breakdown</h2>
      <div className="mt-3 overflow-x-auto rounded-lg border border-[var(--border)] bg-[var(--surface)]">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-[var(--border)] text-xs text-[var(--text-muted)]">
            <tr>
              <th className="px-4 py-2 font-medium">Marketplace</th>
              <th className="px-4 py-2 text-right font-medium">Products</th>
              <th className="px-4 py-2 text-right font-medium">Scanned</th>
              <th className="px-4 py-2 text-right font-medium">Multiple sellers</th>
              <th className="px-4 py-2 text-right font-medium">Offers observed</th>
            </tr>
          </thead>
          <tbody>
            {data?.marketplaces.map((m) => (
              <tr key={m.marketplace} className="border-b border-[var(--border)] last:border-0">
                <td className="px-4 py-2">{m.name}</td>
                <td className="px-4 py-2 text-right tabular-nums">{formatCount(m.products)}</td>
                <td className="px-4 py-2 text-right tabular-nums">{formatCount(m.scanned)}</td>
                <td className="px-4 py-2 text-right">{metricCell(m.with_multiple_sellers)}</td>
                <td className="px-4 py-2 text-right">{metricCell(m.total_offers_observed)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

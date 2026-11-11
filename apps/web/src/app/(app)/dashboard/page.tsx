import type { Metadata } from "next";

import { MetricTile } from "@/components/ui/metric-tile";

export const metadata: Metadata = { title: "Dashboard" };

const NO_DATA = "No scans have run yet.";

// The 7 dashboard KPIs from the product spec. They are wired to the API in milestone M4;
// until then every value is explicitly unavailable rather than shown as 0.
const KPIS = [
  "Total products monitored",
  "Products successfully scanned",
  "Products with multiple sellers",
  "Total offers observed",
  "New sellers detected",
  "Products with unavailable data",
] as const;

export default function DashboardPage() {
  return (
    <section>
      <h1 className="text-2xl font-semibold tracking-tight">Dashboard</h1>
      <p className="mt-1 text-sm text-[var(--text-muted)]">
        Coverage: Amazon.in via the official Selling Partner API. Flipkart is not in the current
        scope.
      </p>
      <div className="mt-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {KPIS.map((label) => (
          <MetricTile key={label} label={label} value={null} unavailableReason={NO_DATA} />
        ))}
      </div>
      <h2 className="mt-8 text-lg font-semibold">Marketplace breakdown</h2>
      <div className="mt-3 rounded-lg border border-[var(--border)] bg-[var(--surface)] p-4 text-sm text-[var(--text-muted)]">
        Not available. {NO_DATA}
      </div>
    </section>
  );
}

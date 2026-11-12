"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";

import { JobProgress, JobStatusBadge } from "@/components/scans/job-status";
import { useSession } from "@/components/session/session-provider";
import { ChangeList } from "@/components/changes/change-list";
import { Alert, errorMessage, Select } from "@/components/ui/form";
import { api } from "@/lib/api";
import { formatCount, formatDateTime } from "@/lib/format";
import { ACTIVE_JOB, type ChangeEvent, type Page, type ScanJob, type ScanQuota } from "@/lib/types";

const TRIGGER_LABELS: Record<ScanJob["trigger"], string> = {
  manual: "Manual",
  scheduled: "Scheduled",
  extension: "Chrome extension",
  api: "API",
};

const EVENT_FILTERS: { value: string; label: string }[] = [
  { value: "", label: "All changes" },
  { value: "seller_newly_observed", label: "New sellers" },
  { value: "seller_no_longer_observed", label: "Sellers gone" },
  { value: "price_changed", label: "Price changes" },
  { value: "offer_count_changed", label: "Offer count changes" },
  { value: "buy_box_changed", label: "Buy Box changes" },
  { value: "scan_unavailable", label: "Data became unavailable" },
];

function ChangesFeed({ orgId }: { orgId: string }) {
  const [eventType, setEventType] = useState("");
  const [showInconclusive, setShowInconclusive] = useState(false);
  const params = new URLSearchParams({ page_size: "100", include_inconclusive: String(showInconclusive) });
  if (eventType) params.set("event_type", eventType);
  const changes = useQuery({
    queryKey: ["tenant", orgId, "changes", params.toString()],
    queryFn: () => api<Page<ChangeEvent>>(`/changes?${params.toString()}`, { orgId }),
  });
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <Select aria-label="Change type" value={eventType} onChange={(e) => setEventType(e.target.value)} className="w-56!">
          {EVENT_FILTERS.map((f) => (
            <option key={f.value} value={f.value}>
              {f.label}
            </option>
          ))}
        </Select>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={showInconclusive} onChange={(e) => setShowInconclusive(e.target.checked)} />
          Include inconclusive (seller missing from an incomplete list)
        </label>
      </div>
      {changes.error && <Alert>{errorMessage(changes.error)}</Alert>}
      {changes.data && (
        <ChangeList events={changes.data.items} empty="No changes detected yet. Changes appear from the second scan of a product." />
      )}
    </div>
  );
}

export default function ScanHistoryPage() {
  const { org } = useSession();
  const [tab, setTab] = useState<"jobs" | "changes">("jobs");
  const jobs = useQuery({
    queryKey: ["tenant", org.id, "scan-jobs"],
    queryFn: () => api<Page<ScanJob>>("/scan-jobs?page_size=50", { orgId: org.id }),
    refetchInterval: (q) => (q.state.data?.items.some((j) => ACTIVE_JOB.includes(j.status)) ? 2000 : false),
  });
  const quota = useQuery({
    queryKey: ["tenant", org.id, "scan-quota"],
    queryFn: () => api<ScanQuota>("/scan-jobs/quota", { orgId: org.id }),
  });

  return (
    <section className="max-w-5xl space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Scan History</h1>
        <p className="mt-1 text-sm text-[var(--text-muted)]">
          Every scan of your products, newest first. Start scans from{" "}
          <Link href="/products" className="text-brand-600">
            Product Mapping
          </Link>
          ; monitored products are also scanned automatically.
        </p>
        {quota.data && quota.data.limit !== null && (
          <p className="mt-2 text-sm">
            Product scans this month: <strong className="tabular-nums">{formatCount(quota.data.used)}</strong> of{" "}
            {formatCount(quota.data.limit)}
          </p>
        )}
      </div>

      <div role="tablist" aria-label="Scan history views" className="flex gap-1">
        {(["jobs", "changes"] as const).map((t) => (
          <button
            key={t}
            role="tab"
            type="button"
            aria-selected={tab === t}
            onClick={() => setTab(t)}
            className={
              tab === t
                ? "bg-brand-50 text-brand-700 dark:bg-brand-700/20 dark:text-brand-100 rounded-md px-3 py-1.5 text-sm font-medium"
                : "rounded-md px-3 py-1.5 text-sm text-[var(--text-muted)] hover:bg-black/5 dark:hover:bg-white/5"
            }
          >
            {t === "jobs" ? "Scans" : "Changes"}
          </button>
        ))}
      </div>

      {tab === "changes" && <ChangesFeed orgId={org.id} />}
      {tab === "jobs" && jobs.error && <Alert>{errorMessage(jobs.error)}</Alert>}
      {tab === "jobs" && jobs.data && jobs.data.items.length === 0 && (
        <p className="text-sm text-[var(--text-muted)]">No scans yet.</p>
      )}
      {tab === "jobs" && jobs.data && jobs.data.items.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-[var(--border)] bg-[var(--surface)]">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-[var(--border)] text-xs text-[var(--text-muted)]">
              <tr>
                <th className="px-4 py-2 font-medium">Started</th>
                <th className="px-4 py-2 font-medium">Type</th>
                <th className="px-4 py-2 font-medium">Status</th>
                <th className="px-4 py-2 font-medium">Progress</th>
                <th className="px-4 py-2 text-right font-medium">Issues</th>
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody>
              {jobs.data.items.map((j) => (
                <tr key={j.id} className="border-b border-[var(--border)] last:border-0">
                  <td className="px-4 py-2 whitespace-nowrap">{formatDateTime(j.created_at)}</td>
                  <td className="px-4 py-2">{TRIGGER_LABELS[j.trigger]}</td>
                  <td className="px-4 py-2">
                    <JobStatusBadge status={j.status} />
                  </td>
                  <td className="px-4 py-2">
                    <JobProgress job={j} />
                  </td>
                  <td className="px-4 py-2 text-right tabular-nums">
                    {j.failed_items + j.unavailable_items > 0 ? formatCount(j.failed_items + j.unavailable_items) : "—"}
                  </td>
                  <td className="px-4 py-2 text-right">
                    <Link href={`/history/${j.id}`} className="text-brand-600 text-xs hover:underline">
                      Details
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

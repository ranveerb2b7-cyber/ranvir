"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";

import { JobProgress, JobStatusBadge } from "@/components/scans/job-status";
import { useSession } from "@/components/session/session-provider";
import { Alert, errorMessage } from "@/components/ui/form";
import { api } from "@/lib/api";
import { formatCount, formatDateTime } from "@/lib/format";
import { ACTIVE_JOB, type Page, type ScanJob, type ScanQuota } from "@/lib/types";

const TRIGGER_LABELS: Record<ScanJob["trigger"], string> = {
  manual: "Manual",
  scheduled: "Scheduled",
  extension: "Chrome extension",
  api: "API",
};

export default function ScanHistoryPage() {
  const { org } = useSession();
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

      {jobs.error && <Alert>{errorMessage(jobs.error)}</Alert>}
      {jobs.data && jobs.data.items.length === 0 && (
        <p className="text-sm text-[var(--text-muted)]">No scans yet.</p>
      )}
      {jobs.data && jobs.data.items.length > 0 && (
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

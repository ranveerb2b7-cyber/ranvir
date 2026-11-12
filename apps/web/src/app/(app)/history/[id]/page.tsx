"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect } from "react";

import { MockBadge } from "@/components/layout/mock-banner";
import { ItemStatusText, JobProgress, JobStatusBadge } from "@/components/scans/job-status";
import { useSession } from "@/components/session/session-provider";
import { Alert, Button, errorMessage } from "@/components/ui/form";
import { Value } from "@/components/ui/value";
import { api } from "@/lib/api";
import { formatCount, formatDateTime, formatPrice } from "@/lib/format";
import { ACTIVE_JOB, MOCK_SOURCE, type Page, type ScanItem, type ScanJob, type ScanJobCreated } from "@/lib/types";

export default function ScanJobPage() {
  const { id } = useParams<{ id: string }>();
  const { org, can } = useSession();
  const router = useRouter();
  const queryClient = useQueryClient();
  const canScan = can("scans.run");

  const job = useQuery({
    queryKey: ["tenant", org.id, "scan-job", id],
    queryFn: () => api<ScanJob>(`/scan-jobs/${id}`, { orgId: org.id }),
    refetchInterval: (q) => (q.state.data && ACTIVE_JOB.includes(q.state.data.status) ? 1500 : false),
  });
  const active = job.data ? ACTIVE_JOB.includes(job.data.status) : false;

  // When a scan finishes, product lists and dashboard numbers cached before it are stale.
  const finished = job.data?.finished_at ?? null;
  useEffect(() => {
    if (!finished) return;
    for (const key of ["products", "dashboard", "scan-jobs", "scan-quota", "alerts"]) {
      void queryClient.invalidateQueries({ queryKey: ["tenant", org.id, key] });
    }
  }, [finished, org.id, queryClient]);
  const items = useQuery({
    queryKey: ["tenant", org.id, "scan-job", id, "items", job.data?.status, job.data && job.data.completed_items + job.data.failed_items],
    queryFn: () => api<Page<ScanItem>>(`/scan-jobs/${id}/items?page_size=200`, { orgId: org.id }),
    enabled: Boolean(job.data),
  });

  const cancel = useMutation({
    mutationFn: () => api<ScanJob>(`/scan-jobs/${id}/cancel`, { method: "POST", orgId: org.id }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["tenant", org.id] }),
  });
  const retry = useMutation({
    mutationFn: () => api<ScanJobCreated>(`/scan-jobs/${id}/retry-failed`, { method: "POST", orgId: org.id }),
    onSuccess: async (created) => {
      await queryClient.invalidateQueries({ queryKey: ["tenant", org.id, "scan-jobs"] });
      router.push(`/history/${created.id}`);
    },
  });

  const back = (
    <Link href="/history" className="text-brand-600 inline-flex items-center gap-1 text-sm">
      <ArrowLeft aria-hidden className="size-4" /> Scan History
    </Link>
  );
  if (job.error) {
    return (
      <section className="space-y-4">
        {back}
        <Alert>{errorMessage(job.error)}</Alert>
      </section>
    );
  }
  const data = job.data;
  if (!data) return <p className="text-sm text-[var(--text-muted)]">Loading…</p>;
  const actionError = cancel.error ?? retry.error;

  return (
    <section className="max-w-6xl space-y-6">
      {back}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Scan of {formatCount(data.total_items)} product(s)</h1>
          <p className="mt-1 text-sm text-[var(--text-muted)]">
            Started {formatDateTime(data.created_at)}
            {data.finished_at && <> · finished {formatDateTime(data.finished_at)}</>}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <JobStatusBadge status={data.status} />
          <JobProgress job={data} />
        </div>
      </div>

      {actionError && <Alert>{errorMessage(actionError)}</Alert>}
      {data.cancel_requested_at && active && (
        <Alert tone="info">Cancelling: products already being scanned will finish first.</Alert>
      )}

      {canScan && (
        <div className="flex flex-wrap gap-2">
          {active && !data.cancel_requested_at && (
            <Button variant="secondary" disabled={cancel.isPending} onClick={() => cancel.mutate()}>
              Cancel scan
            </Button>
          )}
          {!active && data.failed_items > 0 && (
            <Button disabled={retry.isPending} onClick={() => retry.mutate()}>
              Retry {formatCount(data.failed_items)} failed
            </Button>
          )}
        </div>
      )}

      <div className="overflow-x-auto rounded-lg border border-[var(--border)] bg-[var(--surface)]">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-[var(--border)] text-xs text-[var(--text-muted)]">
            <tr>
              <th className="px-3 py-2 font-medium">ASIN</th>
              <th className="px-3 py-2 font-medium">Product</th>
              <th className="px-3 py-2 font-medium">Status</th>
              <th className="px-3 py-2 text-right font-medium">Offers</th>
              <th className="px-3 py-2 text-right font-medium">Unique sellers</th>
              <th className="px-3 py-2 text-right font-medium">Lowest price</th>
              <th className="px-3 py-2 font-medium">Details</th>
            </tr>
          </thead>
          <tbody>
            {items.data?.items.map((i) => {
              const r = i.result && i.result.status !== "error" ? i.result : null;
              return (
                <tr key={i.product_id} className="border-b border-[var(--border)] align-top last:border-0">
                  <td className="px-3 py-2 font-mono text-xs">{i.external_id}</td>
                  <td className="px-3 py-2">{i.product_name ?? "—"}</td>
                  <td className="px-3 py-2 whitespace-nowrap">
                    <ItemStatusText status={i.status} />
                    {r?.data_source === MOCK_SOURCE && <MockBadge />}
                  </td>
                  <td className="px-3 py-2 text-right">
                    {r ? <Value why="The source did not report an offer count.">{formatCount(r.total_offer_count)}</Value> : "—"}
                  </td>
                  <td className="px-3 py-2 text-right">
                    {r ? <Value why="Seller identities were not provided.">{formatCount(r.unique_seller_count)}</Value> : "—"}
                  </td>
                  <td className="px-3 py-2 text-right">
                    {r ? <Value why="No prices observed.">{formatPrice(r.lowest_observed_price, r.currency)}</Value> : "—"}
                  </td>
                  <td className="px-3 py-2 text-xs">
                    {i.last_error_message && (
                      <div className={i.status === "failed" ? "text-red-700 dark:text-red-400" : "text-[var(--text-muted)]"}>
                        {i.last_error_message}
                      </div>
                    )}
                    {i.status === "pending" && i.next_attempt_at && (
                      <div className="text-[var(--text-muted)]">Retrying after {formatDateTime(i.next_attempt_at)}</div>
                    )}
                    {i.attempt_count > 1 && <div className="text-[var(--text-muted)]">{i.attempt_count} attempts</div>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

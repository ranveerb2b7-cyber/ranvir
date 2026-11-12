"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { ArrowLeft, Loader2 } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { useSession } from "@/components/session/session-provider";
import { BatchStatusBadge } from "@/components/uploads/batch-status";
import { Alert, Button, errorMessage } from "@/components/ui/form";
import { api, apiDownload } from "@/lib/api";
import { formatCount, formatDateTime } from "@/lib/format";
import {
  ROW_STATUS_LABELS,
  type BatchDetail,
  type BatchRow,
  type Page,
  type RowStatus,
} from "@/lib/types";

const TABS: RowStatus[] = ["valid", "invalid", "duplicate_in_file", "duplicate_existing"];
const PAGE_SIZE = 50;
const FIELD_LABELS: Record<string, string> = {
  identifier: "ASIN",
  product_name: "Product name",
  brand_name: "Brand",
  marketplace: "Marketplace",
  fsn: "FSN",
};

function countFor(batch: BatchDetail, status: RowStatus): number {
  return {
    valid: batch.valid_rows,
    invalid: batch.invalid_rows,
    duplicate_in_file: batch.duplicate_in_file_rows,
    duplicate_existing: batch.duplicate_existing_rows,
  }[status];
}

function Stat({ label, value, tone }: { label: string; value: number; tone?: "good" | "bad" }) {
  return (
    <div className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-3">
      <div className="text-xs text-[var(--text-muted)]">{label}</div>
      <div
        className={clsx(
          "mt-1 text-2xl font-semibold tabular-nums",
          tone === "good" && "text-green-700 dark:text-green-400",
          tone === "bad" && value > 0 && "text-red-700 dark:text-red-400",
        )}
      >
        {formatCount(value)}
      </div>
    </div>
  );
}

export default function UploadBatchPage() {
  const { id } = useParams<{ id: string }>();
  const { org, can } = useSession();
  const canWrite = can("products.write");
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<RowStatus | null>(null);
  const [page, setPage] = useState(1);

  const batch = useQuery({
    queryKey: ["tenant", org.id, "upload", id],
    queryFn: () => api<BatchDetail>(`/uploads/${id}`, { orgId: org.id }),
    // Poll while the worker is processing the file.
    refetchInterval: (q) => (q.state.data && ["uploaded", "parsing"].includes(q.state.data.status) ? 1500 : false),
  });
  const data = batch.data;
  const ready = data && !["uploaded", "parsing", "failed"].includes(data.status);
  const activeTab: RowStatus = tab ?? (data && data.valid_rows === 0 && data.invalid_rows > 0 ? "invalid" : "valid");

  const rows = useQuery({
    queryKey: ["tenant", org.id, "upload", id, "rows", activeTab, page],
    queryFn: () =>
      api<Page<BatchRow>>(`/uploads/${id}/rows?status=${activeTab}&page=${page}&page_size=${PAGE_SIZE}`, { orgId: org.id }),
    enabled: Boolean(ready),
    placeholderData: keepPreviousData,
  });

  const commit = useMutation({
    mutationFn: () => api<BatchDetail>(`/uploads/${id}/commit`, { method: "POST", orgId: org.id }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["tenant", org.id] }),
  });
  const discard = useMutation({
    mutationFn: () => api(`/uploads/${id}/discard`, { method: "POST", orgId: org.id }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["tenant", org.id] }),
  });
  const [downloadError, setDownloadError] = useState<string | null>(null);

  const back = (
    <Link href="/upload" className="text-brand-600 inline-flex items-center gap-1 text-sm">
      <ArrowLeft aria-hidden className="size-4" /> All uploads
    </Link>
  );

  if (batch.error) {
    return (
      <section className="space-y-4">
        {back}
        <Alert>{errorMessage(batch.error)}</Alert>
      </section>
    );
  }
  if (!data) return <p className="text-sm text-[var(--text-muted)]">Loading…</p>;

  const rejected = data.invalid_rows + data.duplicate_in_file_rows + data.duplicate_existing_rows;
  const remaining = data.plan.remaining;
  const overLimit = remaining !== null && data.valid_rows > remaining;
  const actionError = commit.error ?? discard.error;
  const totalPages = Math.max(1, Math.ceil((rows.data?.total ?? 0) / PAGE_SIZE));

  return (
    <section className="max-w-6xl space-y-6">
      {back}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="truncate text-2xl font-semibold tracking-tight" title={data.original_filename}>
            {data.original_filename}
          </h1>
          <p className="mt-1 text-sm text-[var(--text-muted)]">Uploaded {formatDateTime(data.created_at)}</p>
        </div>
        <BatchStatusBadge status={data.status} />
      </div>

      {(data.status === "uploaded" || data.status === "parsing") && (
        <div role="status" className="flex items-center gap-3 rounded-lg border border-[var(--border)] bg-[var(--surface)] p-4 text-sm">
          <Loader2 aria-hidden className="size-4 animate-spin" />
          Checking your file… This page updates automatically.
        </div>
      )}

      {data.status === "failed" && (
        <Alert>
          <strong>This file couldn&apos;t be processed.</strong> {data.error_message}
        </Alert>
      )}

      {ready && (
        <>
          {data.same_file_as && (
            <Alert tone="info">
              You already added this exact file in an <Link className="underline" href={`/upload/${data.same_file_as}`}>earlier upload</Link>.
            </Alert>
          )}
          {data.status === "committed" && (
            <Alert tone="success">
              Added {formatCount(data.committed_rows)} product(s).{" "}
              <Link className="underline" href="/products">
                View in Product Mapping
              </Link>
            </Alert>
          )}
          {data.status === "discarded" && <Alert tone="info">This upload was discarded. Nothing was added.</Alert>}
          {actionError && <Alert>{errorMessage(actionError)}</Alert>}
          {downloadError && <Alert>{downloadError}</Alert>}

          <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-5">
            <Stat label="Rows in file" value={data.total_rows} />
            <Stat label={data.status === "committed" ? "Added" : "Ready to add"} value={data.status === "committed" ? data.committed_rows : data.valid_rows} tone="good" />
            <Stat label="Invalid" value={data.invalid_rows} tone="bad" />
            <Stat label="Duplicates in file" value={data.duplicate_in_file_rows} />
            <Stat label="Already in products" value={data.duplicate_existing_rows} />
          </div>

          {data.column_mapping && (
            <p className="text-xs text-[var(--text-muted)]">
              Columns used:{" "}
              {Object.entries(data.column_mapping)
                .map(([field, header]) => `${FIELD_LABELS[field] ?? field} ← “${header}”`)
                .join(" · ")}
            </p>
          )}

          {data.status === "preview_ready" && (
            <div className="flex flex-wrap items-center gap-3 rounded-lg border border-[var(--border)] bg-[var(--surface)] p-4">
              <div className="mr-auto text-sm">
                {data.valid_rows === 0 ? (
                  "No new products to add from this file."
                ) : (
                  <>
                    Adds <strong>{formatCount(data.valid_rows)}</strong> product(s).
                    {remaining !== null && (
                      <span className={clsx("ml-1", overLimit ? "text-red-700 dark:text-red-400" : "text-[var(--text-muted)]")}>
                        Your plan has room for {formatCount(remaining)} more.
                      </span>
                    )}
                  </>
                )}
              </div>
              {canWrite && (
                <>
                  <Button variant="secondary" disabled={discard.isPending} onClick={() => discard.mutate()}>
                    Discard
                  </Button>
                  <Button
                    disabled={commit.isPending || data.valid_rows === 0 || overLimit}
                    onClick={() => commit.mutate()}
                  >
                    {commit.isPending ? "Adding…" : `Add ${formatCount(data.valid_rows)} product(s)`}
                  </Button>
                </>
              )}
            </div>
          )}

          <div>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div role="tablist" aria-label="Rows by status" className="flex flex-wrap gap-1">
                {TABS.map((t) => (
                  <button
                    key={t}
                    role="tab"
                    type="button"
                    aria-selected={activeTab === t}
                    onClick={() => {
                      setTab(t);
                      setPage(1);
                    }}
                    className={clsx(
                      "rounded-md px-3 py-1.5 text-sm",
                      activeTab === t
                        ? "bg-brand-50 text-brand-700 dark:bg-brand-700/20 dark:text-brand-100 font-medium"
                        : "text-[var(--text-muted)] hover:bg-black/5 dark:hover:bg-white/5",
                    )}
                  >
                    {ROW_STATUS_LABELS[t]} ({formatCount(countFor(data, t))})
                  </button>
                ))}
              </div>
              {rejected > 0 && (
                <Button
                  variant="secondary"
                  onClick={() => {
                    setDownloadError(null);
                    apiDownload(`/uploads/${id}/rejected.csv`, org.id, "rejected-rows.csv").catch((e: unknown) =>
                      setDownloadError(errorMessage(e)),
                    );
                  }}
                >
                  Download rejected rows (CSV)
                </Button>
              )}
            </div>

            <div className="mt-3 overflow-x-auto rounded-lg border border-[var(--border)] bg-[var(--surface)]">
              <table className="w-full text-left text-sm">
                <thead className="border-b border-[var(--border)] text-xs text-[var(--text-muted)]">
                  <tr>
                    <th className="px-3 py-2 font-medium">Row</th>
                    <th className="px-3 py-2 font-medium">ASIN</th>
                    <th className="px-3 py-2 font-medium">Product name</th>
                    <th className="px-3 py-2 font-medium">Brand</th>
                    <th className="px-3 py-2 font-medium">{activeTab === "valid" ? "Notes" : "Reason"}</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.data?.items.length === 0 && (
                    <tr>
                      <td colSpan={5} className="px-3 py-4 text-center text-[var(--text-muted)]">
                        No rows in this group.
                      </td>
                    </tr>
                  )}
                  {rows.data?.items.map((r) => {
                    const input = r.asin ?? Object.values(r.original)[0] ?? "";
                    return (
                      <tr key={r.row_number} className="border-b border-[var(--border)] align-top last:border-0">
                        <td className="px-3 py-2 tabular-nums text-[var(--text-muted)]">{r.row_number}</td>
                        <td className="px-3 py-2 font-mono text-xs break-all">{r.asin ?? <span className="text-[var(--text-muted)]">{input || "—"}</span>}</td>
                        <td className="px-3 py-2">{r.product_name ?? "—"}</td>
                        <td className="px-3 py-2">{r.brand_name ?? "—"}</td>
                        <td className="px-3 py-2 text-xs">
                          {r.errors.map((e) => (
                            <div key={e.code} className="text-red-700 dark:text-red-400">
                              {e.message}
                            </div>
                          ))}
                          {r.warnings.map((w) => (
                            <div key={w.code} className="text-amber-700 dark:text-amber-400">
                              {w.message}
                            </div>
                          ))}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            {totalPages > 1 && (
              <div className="mt-3 flex items-center justify-end gap-2 text-sm">
                <Button variant="secondary" disabled={page <= 1} onClick={() => setPage(page - 1)}>
                  Previous
                </Button>
                <span>
                  Page {page} of {totalPages}
                </span>
                <Button variant="secondary" disabled={page >= totalPages} onClick={() => setPage(page + 1)}>
                  Next
                </Button>
              </div>
            )}
          </div>
        </>
      )}
    </section>
  );
}

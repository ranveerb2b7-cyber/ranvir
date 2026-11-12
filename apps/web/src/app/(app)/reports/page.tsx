"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { Download } from "lucide-react";
import { useState, type FormEvent } from "react";

import { MockBadge } from "@/components/layout/mock-banner";
import { useSession } from "@/components/session/session-provider";
import { Alert, Button, errorMessage, Field, Input, Select } from "@/components/ui/form";
import { api, apiDownload } from "@/lib/api";
import { formatCount, formatDateTime } from "@/lib/format";
import { describeFilters, formatBytes, REPORT_TYPE_ORDER, REPORT_TYPES } from "@/lib/reports";
import type { BrandCount, ReportExport, ReportFormat, ReportPage, ReportType } from "@/lib/types";

const ACTIVE = ["queued", "running"];
const STATUS_STYLE: Record<ReportExport["status"], string> = {
  queued: "text-[var(--text-muted)]",
  running: "text-[var(--text-muted)]",
  completed: "text-green-700 dark:text-green-300",
  failed: "text-red-700 dark:text-red-300",
  expired: "text-[var(--text-muted)]",
};
const STATUS_LABEL: Record<ReportExport["status"], string> = {
  queued: "Waiting…",
  running: "Preparing…",
  completed: "Ready",
  failed: "Failed",
  expired: "Expired",
};

function NewReport({ orgId }: { orgId: string }) {
  const queryClient = useQueryClient();
  const [type, setType] = useState<ReportType>("product");
  const [format, setFormat] = useState<ReportFormat>("xlsx");
  const [brand, setBrand] = useState("");
  const [monitoring, setMonitoring] = useState("");
  const [tag, setTag] = useState("");
  const [offering, setOffering] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [alertStatus, setAlertStatus] = useState("");
  const kind = REPORT_TYPES[type].filters;
  const brands = useQuery({
    queryKey: ["tenant", orgId, "brands"],
    queryFn: () => api<BrandCount[]>("/brands", { orgId }),
    enabled: kind === "product",
  });

  const create = useMutation({
    mutationFn: (body: Record<string, unknown>) => api<ReportExport>("/reports", { method: "POST", orgId, body }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["tenant", orgId, "reports"] }),
  });

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const filters: Record<string, unknown> = {};
    if (kind === "product") {
      if (brand) filters.brand = brand;
      if (monitoring) filters.monitoring = monitoring === "true";
    }
    if (kind === "seller") {
      if (tag.trim()) filters.tag = tag.trim();
      if (offering) filters.currently_offering = offering === "true";
    }
    if (kind === "dates" || kind === "alerts") {
      if (from) filters.date_from = from;
      if (to) filters.date_to = to;
    }
    if (kind === "alerts" && alertStatus) filters.status = alertStatus;
    create.mutate({ report_type: type, format, filters });
  }

  return (
    <form onSubmit={submit} className="space-y-4 rounded-lg border border-[var(--border)] bg-[var(--surface)] p-4">
      <h2 className="font-semibold">New report</h2>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Report" htmlFor="report-type" hint={REPORT_TYPES[type].description}>
          <Select id="report-type" value={type} onChange={(e) => setType(e.target.value as ReportType)}>
            {REPORT_TYPE_ORDER.map((t) => (
              <option key={t} value={t}>
                {REPORT_TYPES[t].label}
              </option>
            ))}
          </Select>
        </Field>
        <fieldset>
          <legend className="mb-1 block text-sm font-medium">Format</legend>
          <div className="flex gap-4 py-2">
            {(
              [
                ["xlsx", "Excel (.xlsx)"],
                ["csv", "CSV"],
              ] as const
            ).map(([value, label]) => (
              <label key={value} className="inline-flex items-center gap-2 text-sm">
                <input type="radio" name="format" checked={format === value} onChange={() => setFormat(value)} />
                {label}
              </label>
            ))}
          </div>
        </fieldset>
      </div>

      {kind === "product" && (
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Brand" htmlFor="report-brand">
            <Select id="report-brand" value={brand} onChange={(e) => setBrand(e.target.value)}>
              <option value="">All brands</option>
              {(brands.data ?? []).map((b) => (
                <option key={b.brand_name ?? "__none__"} value={b.brand_name ?? "__none__"}>
                  {b.brand_name ?? "(no brand)"} ({formatCount(b.products)})
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Monitoring" htmlFor="report-monitoring">
            <Select id="report-monitoring" value={monitoring} onChange={(e) => setMonitoring(e.target.value)}>
              <option value="">All products</option>
              <option value="true">Monitored only</option>
              <option value="false">Not monitored</option>
            </Select>
          </Field>
        </div>
      )}
      {kind === "seller" && (
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Tag" htmlFor="report-tag" hint="Only sellers with this tag (optional).">
            <Input id="report-tag" maxLength={40} value={tag} onChange={(e) => setTag(e.target.value)} />
          </Field>
          <Field label="Offering now" htmlFor="report-offering">
            <Select id="report-offering" value={offering} onChange={(e) => setOffering(e.target.value)}>
              <option value="">All sellers</option>
              <option value="true">Offering one of my products now</option>
              <option value="false">Not offering now</option>
            </Select>
          </Field>
        </div>
      )}
      {(kind === "dates" || kind === "alerts") && (
        <div className="grid gap-4 sm:grid-cols-3">
          <Field label="From" htmlFor="report-from" hint="Leave both empty for the last 30 days (UTC).">
            <Input id="report-from" type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
          </Field>
          <Field label="To" htmlFor="report-to">
            <Input id="report-to" type="date" value={to} onChange={(e) => setTo(e.target.value)} />
          </Field>
          {kind === "alerts" && (
            <Field label="Status" htmlFor="report-alert-status">
              <Select id="report-alert-status" value={alertStatus} onChange={(e) => setAlertStatus(e.target.value)}>
                <option value="">All</option>
                <option value="open">Open</option>
                <option value="acknowledged">Acknowledged</option>
                <option value="resolved">Resolved</option>
              </Select>
            </Field>
          )}
        </div>
      )}

      {create.error && <Alert>{errorMessage(create.error)}</Alert>}
      {create.isSuccess && !create.isPending && (
        <Alert tone="success">Report requested. It appears below and can be downloaded when ready.</Alert>
      )}
      <Button type="submit" disabled={create.isPending}>
        Create report
      </Button>
    </form>
  );
}

export default function ReportsPage() {
  const { org, me, can } = useSession();
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const reports = useQuery({
    queryKey: ["tenant", org.id, "reports", page],
    queryFn: () => api<ReportPage>(`/reports?page=${page}&page_size=25`, { orgId: org.id }),
    refetchInterval: (q) => (q.state.data?.items.some((r) => ACTIVE.includes(r.status)) ? 2000 : false),
  });
  const download = useMutation({
    mutationFn: (r: ReportExport) => apiDownload(`/reports/${r.id}/download`, org.id, r.file_name ?? "report"),
  });
  const remove = useMutation({
    mutationFn: (id: string) => api(`/reports/${id}`, { method: "DELETE", orgId: org.id }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["tenant", org.id, "reports"] }),
  });
  const items = reports.data?.items ?? [];
  const pages = reports.data ? Math.max(1, Math.ceil(reports.data.total / reports.data.page_size)) : 1;

  return (
    <section className="max-w-5xl space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Reports</h1>
        <p className="mt-1 text-sm text-[var(--text-muted)]">
          Export your data as Excel or CSV. Reports are prepared in the background and kept for{" "}
          {reports.data?.retention_days ?? 7} days. Missing values are left empty (never 0) and each file explains why.
        </p>
      </div>
      <NewReport orgId={org.id} />

      {(reports.error ?? download.error ?? remove.error) && (
        <Alert>{errorMessage(reports.error ?? download.error ?? remove.error)}</Alert>
      )}
      {reports.data && items.length === 0 && <p className="text-sm text-[var(--text-muted)]">No reports yet.</p>}
      {items.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-[var(--border)] bg-[var(--surface)]">
          <table className="w-full text-left text-sm" aria-label="Reports">
            <thead className="border-b border-[var(--border)] text-xs text-[var(--text-muted)]">
              <tr>
                <th className="px-4 py-2 font-medium">Report</th>
                <th className="hidden px-4 py-2 font-medium sm:table-cell">Requested</th>
                <th className="px-4 py-2 font-medium">Status</th>
                <th className="hidden px-4 py-2 text-right font-medium sm:table-cell">Rows</th>
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody>
              {items.map((r) => (
                <tr key={r.id} className="border-b border-[var(--border)] align-top last:border-0">
                  <td className="px-4 py-2">
                    <div className="font-medium">
                      {REPORT_TYPES[r.report_type].label}{" "}
                      <span className="text-xs font-normal text-[var(--text-muted)] uppercase">{r.format}</span>
                    </div>
                    <div className="text-xs text-[var(--text-muted)]">{describeFilters(r)}</div>
                    <div className="text-xs text-[var(--text-muted)] sm:hidden">
                      {formatDateTime(r.created_at)}
                      {r.row_count !== null && ` · ${formatCount(r.row_count)} rows`}
                    </div>
                  </td>
                  <td className="hidden px-4 py-2 text-xs sm:table-cell">
                    <div className="whitespace-nowrap">{formatDateTime(r.created_at)}</div>
                    <div className="text-[var(--text-muted)]">{r.requested_by_email ?? "Former member"}</div>
                  </td>
                  <td className="px-4 py-2 text-xs">
                    <span className={clsx("font-medium", STATUS_STYLE[r.status])}>{STATUS_LABEL[r.status]}</span>
                    {r.contains_mock && (
                      <span className="ml-2">
                        <MockBadge />
                      </span>
                    )}
                    {r.status === "failed" && r.error_message && <div className="mt-0.5 text-red-700 dark:text-red-300">{r.error_message}</div>}
                    {r.status === "completed" && r.expires_at && (
                      <div className="text-[var(--text-muted)]">
                        {formatBytes(r.size_bytes)} · until {formatDateTime(r.expires_at)}
                      </div>
                    )}
                  </td>
                  <td className="hidden px-4 py-2 text-right tabular-nums sm:table-cell">{formatCount(r.row_count) ?? "—"}</td>
                  <td className="px-4 py-2 text-right">
                    {r.status === "completed" && (
                      <Button variant="secondary" className="px-2! py-1! text-xs" onClick={() => download.mutate(r)} aria-label={`Download ${r.file_name}`}>
                        <Download aria-hidden className="mr-1 size-3.5" /> Download
                      </Button>
                    )}
                    {(r.requested_by === me.id || can("org.manage")) && r.status !== "running" && (
                      <button
                        type="button"
                        className="ml-3 text-xs text-red-700 hover:underline dark:text-red-300"
                        onClick={() => remove.mutate(r.id)}
                      >
                        Delete
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {reports.data && pages > 1 && (
        <div className="flex items-center justify-end gap-2 text-sm">
          <Button variant="secondary" disabled={page <= 1} onClick={() => setPage(page - 1)}>
            Previous
          </Button>
          <span className="tabular-nums">
            Page {page} of {pages}
          </span>
          <Button variant="secondary" disabled={page >= pages} onClick={() => setPage(page + 1)}>
            Next
          </Button>
        </div>
      )}
    </section>
  );
}

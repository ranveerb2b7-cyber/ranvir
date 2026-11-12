"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { Mail, MailWarning, Plus } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { RuleDialog } from "@/components/alerts/rule-dialog";
import { SeverityBadge } from "@/components/alerts/severity";
import { useSession } from "@/components/session/session-provider";
import { Alert, Button, errorMessage, Select } from "@/components/ui/form";
import { describeRule, RULE_TYPES } from "@/lib/alerts";
import { api } from "@/lib/api";
import { formatCount, formatDateTime } from "@/lib/format";
import type { AlertItem, AlertRule, AlertRuleList, AlertSummary, Page } from "@/lib/types";

type Tab = "inbox" | "rules";
const STATUS_FILTERS = [
  { value: "active", label: "Needs attention" },
  { value: "open", label: "Open" },
  { value: "acknowledged", label: "Acknowledged" },
  { value: "resolved", label: "Resolved" },
  { value: "", label: "All" },
] as const;

function EmailStatus({ alert, canRetry, onRetry }: { alert: AlertItem; canRetry: boolean; onRetry: () => void }) {
  const emails = alert.deliveries.filter((d) => d.channel === "email");
  if (emails.length === 0) return null;
  const sent = emails.filter((d) => d.status === "sent").length;
  const failed = emails.filter((d) => d.status === "failed");
  const retrying = emails.filter((d) => d.status === "pending" && d.attempt_count > 0);
  const waiting = emails.filter((d) => (d.status === "pending" && d.attempt_count === 0) || d.status === "sending");
  const skipped = emails.filter((d) => d.status === "skipped");
  const problem = failed[0] ?? retrying[0];
  return (
    <p className={clsx("mt-1 flex flex-wrap items-center gap-x-2 text-xs", problem ? "text-red-700 dark:text-red-300" : "text-[var(--text-muted)]")}>
      {problem ? <MailWarning aria-hidden className="size-3.5" /> : <Mail aria-hidden className="size-3.5" />}
      {sent > 0 && <span>Emailed to {sent}</span>}
      {waiting.length > 0 && <span>Email queued ({waiting.length})</span>}
      {retrying.length > 0 && (
        <span>
          Email failed, retrying {formatDateTime(retrying[0]?.next_attempt_at)} ({retrying.length})
        </span>
      )}
      {failed.length > 0 && <span>Email failed after {failed[0]?.attempt_count} attempts ({failed.length})</span>}
      {problem?.last_error && <span className="break-all">· {problem.last_error}</span>}
      {skipped.length > 0 && <span className="text-[var(--text-muted)]">· {skipped.length} not sent (no longer a member)</span>}
      {failed.length > 0 && canRetry && (
        <button type="button" onClick={onRetry} className="text-brand-600 hover:underline">
          Retry email
        </button>
      )}
    </p>
  );
}

function statusText(a: AlertItem): string {
  if (a.status === "resolved")
    return a.resolved_automatically
      ? `Resolved automatically ${formatDateTime(a.resolved_at)} (condition cleared on a later scan)`
      : `Resolved ${formatDateTime(a.resolved_at)}`;
  if (a.status === "acknowledged") return `Acknowledged ${formatDateTime(a.acknowledged_at)}`;
  return "Open";
}

function Inbox({ orgId, highlight }: { orgId: string; highlight: string | null }) {
  const { can } = useSession();
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<string>("active");
  const [severity, setSeverity] = useState("");
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const params = new URLSearchParams({ page: String(page), page_size: "25" });
  if (status === "active") params.set("active", "true");
  else if (status) params.set("status", status);
  if (severity) params.set("severity", severity);

  const list = useQuery({
    queryKey: ["tenant", orgId, "alerts", "list", params.toString()],
    queryFn: () => api<Page<AlertItem>>(`/alerts?${params.toString()}`, { orgId }),
  });
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["tenant", orgId, "alerts"] });
  const act = useMutation({
    mutationFn: ({ ids, action }: { ids: string[]; action: "acknowledge" | "resolve" }) =>
      ids.length === 1
        ? api(`/alerts/${ids[0]}/${action}`, { method: "POST", orgId })
        : api("/alerts/bulk", { method: "POST", orgId, body: { ids, action } }),
    onSuccess: async () => {
      setSelected(new Set());
      await refresh();
    },
  });
  const retry = useMutation({
    mutationFn: (id: string) => api(`/alerts/${id}/retry-delivery`, { method: "POST", orgId }),
    onSuccess: refresh,
  });

  const items = list.data?.items ?? [];
  const pages = list.data ? Math.max(1, Math.ceil(list.data.total / list.data.page_size)) : 1;
  const resetPage = () => {
    setPage(1);
    setSelected(new Set());
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <Select aria-label="Status" value={status} onChange={(e) => (setStatus(e.target.value), resetPage())} className="w-48!">
          {STATUS_FILTERS.map((f) => (
            <option key={f.value} value={f.value}>
              {f.label}
            </option>
          ))}
        </Select>
        <Select aria-label="Severity" value={severity} onChange={(e) => (setSeverity(e.target.value), resetPage())} className="w-40!">
          <option value="">All severities</option>
          <option value="critical">Critical</option>
          <option value="warning">Warning</option>
          <option value="info">Info</option>
        </Select>
        {selected.size > 0 && (
          <div className="flex items-center gap-2 text-sm">
            <span>{selected.size} selected</span>
            <Button variant="secondary" onClick={() => act.mutate({ ids: [...selected], action: "acknowledge" })}>
              Acknowledge
            </Button>
            <Button variant="secondary" onClick={() => act.mutate({ ids: [...selected], action: "resolve" })}>
              Resolve
            </Button>
          </div>
        )}
      </div>
      {(list.error ?? act.error ?? retry.error) && <Alert>{errorMessage(list.error ?? act.error ?? retry.error)}</Alert>}
      {list.data && items.length === 0 && (
        <p className="rounded-lg border border-[var(--border)] bg-[var(--surface)] px-4 py-6 text-center text-sm text-[var(--text-muted)]">
          {status === "active" ? "Nothing needs attention." : "No alerts match these filters."} Alerts are raised by your rules after each scan.
        </p>
      )}
      {items.length > 0 && (
        <ol className="divide-y divide-[var(--border)] rounded-lg border border-[var(--border)] bg-[var(--surface)]" aria-label="Alerts">
          {items.map((a) => (
            <li
              key={a.id}
              id={`alert-${a.id}`}
              className={clsx("flex gap-3 px-4 py-3 text-sm", highlight === a.id && "bg-brand-50 dark:bg-brand-700/20")}
            >
              <input
                type="checkbox"
                className="mt-1"
                aria-label={`Select: ${a.title}`}
                disabled={a.status === "resolved"}
                checked={selected.has(a.id)}
                onChange={(e) => {
                  const next = new Set(selected);
                  if (e.target.checked) next.add(a.id);
                  else next.delete(a.id);
                  setSelected(next);
                }}
              />
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <SeverityBadge severity={a.severity} />
                  <span data-alert-title className={clsx("font-medium", a.status === "resolved" && "text-[var(--text-muted)]")}>
                    {a.title}
                  </span>
                </div>
                {a.body && <p className="mt-1 text-[var(--text-muted)]">{a.body}</p>}
                <p className="mt-1 text-xs text-[var(--text-muted)]">
                  {formatDateTime(a.created_at)}
                  {a.product && (
                    <>
                      {" · "}
                      <Link href={`/products/${a.product.id}`} className="text-brand-600 font-mono">
                        {a.product.external_id}
                      </Link>
                    </>
                  )}
                  {a.seller && (
                    <>
                      {" · "}
                      <Link href={`/sellers/${a.seller.id}`} className="text-brand-600">
                        seller {a.seller.display_name ?? a.seller.external_seller_id}
                      </Link>
                    </>
                  )}
                  {a.rule_name && ` · Rule: ${a.rule_name}${a.alert_rule_id ? "" : " (deleted)"}`}
                  {` · ${statusText(a)}`}
                </p>
                <EmailStatus alert={a} canRetry={can("alerts.manage")} onRetry={() => retry.mutate(a.id)} />
              </div>
              <div className="flex shrink-0 flex-col items-end gap-1 self-start sm:flex-row">
                {a.status === "open" && (
                  <Button variant="secondary" className="px-2! py-1! text-xs" onClick={() => act.mutate({ ids: [a.id], action: "acknowledge" })}>
                    Acknowledge
                  </Button>
                )}
                {a.status !== "resolved" && (
                  <Button variant="secondary" className="px-2! py-1! text-xs" onClick={() => act.mutate({ ids: [a.id], action: "resolve" })}>
                    Resolve
                  </Button>
                )}
              </div>
            </li>
          ))}
        </ol>
      )}
      {list.data && pages > 1 && (
        <div className="flex items-center justify-end gap-2 text-sm">
          <Button variant="secondary" disabled={page <= 1} onClick={() => setPage(page - 1)}>
            Previous
          </Button>
          <span className="tabular-nums">
            Page {list.data.page} of {pages}
          </span>
          <Button variant="secondary" disabled={page >= pages} onClick={() => setPage(page + 1)}>
            Next
          </Button>
        </div>
      )}
    </div>
  );
}

function Rules({ orgId }: { orgId: string }) {
  const { can } = useSession();
  const manage = can("alerts.manage");
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState<AlertRule | null | undefined>(undefined);
  const rules = useQuery({
    queryKey: ["tenant", orgId, "alert-rules"],
    queryFn: () => api<AlertRuleList>("/alert-rules", { orgId }),
  });
  // The toggle flips at once (set synchronously); it falls back to the server's value after.
  const [toggling, setToggling] = useState<Record<string, boolean>>({});
  const update = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Partial<AlertRule> }) =>
      api(`/alert-rules/${id}`, { method: "PATCH", orgId, body }),
    onSettled: async (_data, _error, { id }) => {
      await queryClient.invalidateQueries({ queryKey: ["tenant", orgId, "alert-rules"] });
      setToggling((prev) => {
        const next = { ...prev };
        delete next[id];
        return next;
      });
    },
  });
  const remove = useMutation({
    mutationFn: (id: string) => api(`/alert-rules/${id}`, { method: "DELETE", orgId }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["tenant", orgId] }),
  });
  const items = rules.data?.items ?? [];

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-[var(--text-muted)]">
          Rules are checked after every scan. Changing a rule affects future scans only.
          {!manage && " Your role can view rules but not change them."}
        </p>
        {manage && (
          <Button onClick={() => setEditing(null)} disabled={rules.data !== undefined && items.length >= rules.data.limit}>
            <Plus aria-hidden className="mr-1 size-4" /> New rule
          </Button>
        )}
      </div>
      {(rules.error ?? update.error ?? remove.error) && <Alert>{errorMessage(rules.error ?? update.error ?? remove.error)}</Alert>}
      {rules.data && items.length === 0 && (
        <p className="rounded-lg border border-[var(--border)] bg-[var(--surface)] px-4 py-6 text-center text-sm text-[var(--text-muted)]">
          No alert rules yet.{manage && " Create one to be told about new sellers, price drops and more."}
        </p>
      )}
      {items.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-[var(--border)] bg-[var(--surface)]">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-[var(--border)] text-xs text-[var(--text-muted)]">
              <tr>
                <th className="px-4 py-2 font-medium">Rule</th>
                <th className="px-4 py-2 font-medium">Products</th>
                <th className="px-4 py-2 font-medium">Severity</th>
                <th className="px-4 py-2 font-medium">Notify</th>
                <th className="px-4 py-2 text-right font-medium">Unresolved</th>
                <th className="px-4 py-2 font-medium">Enabled</th>
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody>
              {items.map((r) => (
                <tr key={r.id} className="border-b border-[var(--border)] last:border-0">
                  <td className="px-4 py-2">
                    <div className="font-medium">{r.name}</div>
                    <div className="text-xs text-[var(--text-muted)]">
                      {RULE_TYPES[r.rule_type].label}: {describeRule(r)}
                    </div>
                  </td>
                  <td className="px-4 py-2 text-xs">
                    {r.scope.product_ids.length > 0
                      ? `${formatCount(r.scope.product_ids.length)} selected`
                      : r.scope.brands.length > 0
                        ? `Brands: ${r.scope.brands.join(", ")}`
                        : "All"}
                  </td>
                  <td className="px-4 py-2">
                    <SeverityBadge severity={r.severity} />
                  </td>
                  <td className="px-4 py-2 text-xs">
                    {r.channels.includes("email") ? `In app + email (${r.recipient_user_ids.length})` : "In app"}
                  </td>
                  <td className="px-4 py-2 text-right tabular-nums">{formatCount(r.open_alerts)}</td>
                  <td className="px-4 py-2">
                    <label className="inline-flex items-center gap-2 text-xs">
                      <input
                        type="checkbox"
                        checked={toggling[r.id] ?? r.is_enabled}
                        disabled={!manage || r.id in toggling}
                        onChange={(e) => {
                          const enabled = e.target.checked;
                          setToggling((prev) => ({ ...prev, [r.id]: enabled }));
                          update.mutate({ id: r.id, body: { is_enabled: enabled } });
                        }}
                        aria-label={`Enable ${r.name}`}
                      />
                      {(toggling[r.id] ?? r.is_enabled) ? "On" : "Off"}
                    </label>
                  </td>
                  <td className="px-4 py-2 text-right whitespace-nowrap">
                    {manage && (
                      <>
                        <button type="button" className="text-brand-600 text-xs hover:underline" onClick={() => setEditing(r)}>
                          Edit
                        </button>
                        <button
                          type="button"
                          className="ml-3 text-xs text-red-700 hover:underline dark:text-red-300"
                          onClick={() => {
                            if (window.confirm(`Delete the rule "${r.name}"? Its past alerts are kept.`)) remove.mutate(r.id);
                          }}
                        >
                          Delete
                        </button>
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <RuleDialog orgId={orgId} rule={editing ?? null} open={editing !== undefined} onClose={() => setEditing(undefined)} />
    </div>
  );
}

function AlertsView() {
  const { org } = useSession();
  const router = useRouter();
  const search = useSearchParams();
  const tab: Tab = search.get("tab") === "rules" ? "rules" : "inbox";
  const summary = useQuery({
    queryKey: ["tenant", org.id, "alerts", "summary"],
    queryFn: () => api<AlertSummary>("/alerts/summary", { orgId: org.id }),
  });
  const s = summary.data;

  return (
    <section className="max-w-5xl space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Alerts</h1>
        {s && (
          <p className="mt-1 text-sm text-[var(--text-muted)]">
            <strong className="text-[var(--text)] tabular-nums">{formatCount(s.open)}</strong> open (
            {formatCount(s.open_by_severity.critical)} critical, {formatCount(s.open_by_severity.warning)} warning,{" "}
            {formatCount(s.open_by_severity.info)} info) · {formatCount(s.acknowledged)} acknowledged
          </p>
        )}
      </div>
      {s && s.failed_deliveries > 0 && (
        <Alert>
          {formatCount(s.failed_deliveries)} alert email{s.failed_deliveries === 1 ? "" : "s"} could not be sent after
          several attempts. The error is shown on each alert; check the email (SMTP) settings, then retry.
        </Alert>
      )}
      <div role="tablist" aria-label="Alert views" className="flex gap-1">
        {(["inbox", "rules"] as const).map((t) => (
          <button
            key={t}
            role="tab"
            type="button"
            aria-selected={tab === t}
            onClick={() => router.replace(t === "rules" ? "/alerts?tab=rules" : "/alerts")}
            className={
              tab === t
                ? "bg-brand-50 text-brand-700 dark:bg-brand-700/20 dark:text-brand-100 rounded-md px-3 py-1.5 text-sm font-medium"
                : "rounded-md px-3 py-1.5 text-sm text-[var(--text-muted)] hover:bg-black/5 dark:hover:bg-white/5"
            }
          >
            {t === "inbox" ? "Inbox" : "Rules"}
          </button>
        ))}
      </div>
      {tab === "inbox" ? <Inbox orgId={org.id} highlight={search.get("alert")} /> : <Rules orgId={org.id} />}
    </section>
  );
}

export default function AlertsPage() {
  return (
    <Suspense>
      <AlertsView />
    </Suspense>
  );
}

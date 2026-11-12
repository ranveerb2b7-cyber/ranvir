"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { X } from "lucide-react";
import { useState, type FormEvent } from "react";

import { Dialog } from "@/components/ui/dialog";
import { Alert, Button, errorMessage, Field, Input, Select } from "@/components/ui/form";
import { RULE_TYPE_ORDER, RULE_TYPES, SEVERITY_LABELS, type ParamField } from "@/lib/alerts";
import { api, ApiError } from "@/lib/api";
import type { AlertRule, AlertRuleType, AlertSeverity, Member, Page, Product } from "@/lib/types";

type ParamValues = Record<string, string | boolean>;
type ScopeMode = "all" | "brands" | "products";

function initialParams(type: AlertRuleType, params: Record<string, unknown> = {}): ParamValues {
  const values: ParamValues = {};
  for (const f of RULE_TYPES[type].fields) {
    const v = params[f.key];
    if (f.kind === "boolean") values[f.key] = v === true;
    else if (f.kind === "tags") values[f.key] = Array.isArray(v) ? v.join(", ") : "";
    else if (f.kind === "select") values[f.key] = typeof v === "string" ? v : (f.options[0]?.value ?? "");
    else values[f.key] = v === undefined || v === null ? "" : String(v);
  }
  return values;
}

function toParams(type: AlertRuleType, values: ParamValues): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const f of RULE_TYPES[type].fields) {
    const v = values[f.key];
    if (f.kind === "boolean") out[f.key] = v === true;
    else if (f.kind === "tags")
      out[f.key] = String(v ?? "")
        .split(",")
        .map((t) => t.trim())
        .filter(Boolean);
    else if (f.kind === "number") {
      if (v === "" || v === undefined) continue; // server applies the default, or rejects a required one
      // Prices stay strings (exact decimals); counts are integers.
      out[f.key] = f.step ? String(v) : Number(v);
    } else out[f.key] = v;
  }
  return out;
}

function ParamInput({ field, value, onChange }: { field: ParamField; value: string | boolean; onChange: (v: string | boolean) => void }) {
  const id = `param-${field.key}`;
  if (field.kind === "boolean")
    return (
      <label className="flex items-start gap-2 text-sm">
        <input type="checkbox" className="mt-0.5" checked={value === true} onChange={(e) => onChange(e.target.checked)} />
        <span>
          {field.label}
          {field.hint && <span className="block text-xs text-[var(--text-muted)]">{field.hint}</span>}
        </span>
      </label>
    );
  if (field.kind === "select")
    return (
      <Field label={field.label} htmlFor={id}>
        <Select id={id} value={String(value)} onChange={(e) => onChange(e.target.value)}>
          {field.options.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </Select>
      </Field>
    );
  return (
    <Field label={field.label} htmlFor={id} hint={field.hint}>
      <Input
        id={id}
        type={field.kind === "number" ? "number" : "text"}
        inputMode={field.kind === "number" ? "decimal" : undefined}
        min={field.kind === "number" ? field.min : undefined}
        step={field.kind === "number" ? (field.step ?? "1") : undefined}
        required={field.kind === "number" && field.required}
        value={String(value)}
        onChange={(e) => onChange(e.target.value)}
      />
    </Field>
  );
}

function ProductPicker({ orgId, selected, labels, onChange }: {
  orgId: string;
  selected: Map<string, string>;
  /** ASINs of already-selected products (when editing a rule). */
  labels: Map<string, string> | undefined;
  onChange: (next: Map<string, string>) => void;
}) {
  const [q, setQ] = useState("");
  const results = useQuery({
    queryKey: ["tenant", orgId, "products", "picker", q],
    queryFn: () => api<Page<Product>>(`/products?page_size=8&q=${encodeURIComponent(q)}`, { orgId }),
    enabled: q.trim().length > 0,
  });
  return (
    <div className="space-y-2">
      <Input aria-label="Search products" placeholder="Search by ASIN, name or brand" value={q} onChange={(e) => setQ(e.target.value)} />
      {results.data && (
        <ul className="max-h-40 overflow-auto rounded-md border border-[var(--border)] text-sm">
          {results.data.items.length === 0 && <li className="px-3 py-2 text-[var(--text-muted)]">No matches</li>}
          {results.data.items.map((p) => (
            <li key={p.id}>
              <label className="flex items-center gap-2 px-3 py-1.5 hover:bg-black/5 dark:hover:bg-white/5">
                <input
                  type="checkbox"
                  checked={selected.has(p.id)}
                  onChange={(e) => {
                    const next = new Map(selected);
                    if (e.target.checked) next.set(p.id, p.external_id);
                    else next.delete(p.id);
                    onChange(next);
                  }}
                />
                <span className="font-mono text-xs">{p.external_id}</span>
                <span className="truncate text-[var(--text-muted)]">{p.product_name}</span>
              </label>
            </li>
          ))}
        </ul>
      )}
      {selected.size > 0 && (
        <ul className="flex flex-wrap gap-1" aria-label="Selected products">
          {[...selected].map(([id, fallback]) => {
            const label = labels?.get(id) ?? fallback;
            return (
            <li key={id} className="inline-flex items-center gap-1 rounded-full border border-[var(--border)] px-2 py-0.5 font-mono text-xs">
              {label}
              <button
                type="button"
                aria-label={`Remove ${label}`}
                onClick={() => {
                  const next = new Map(selected);
                  next.delete(id);
                  onChange(next);
                }}
              >
                <X aria-hidden className="size-3" />
              </button>
            </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

export function RuleDialog({ orgId, rule, open, onClose }: {
  orgId: string;
  /** Edit this rule; null creates a new one. */
  rule: AlertRule | null;
  open: boolean;
  onClose: () => void;
}) {
  return (
    <Dialog open={open} title={rule ? "Edit alert rule" : "New alert rule"} onClose={onClose}>
      {/* Re-mount per rule so the form starts from that rule's values. */}
      <RuleForm key={rule?.id ?? "new"} orgId={orgId} rule={rule} onDone={onClose} />
    </Dialog>
  );
}

function RuleForm({ orgId, rule, onDone }: { orgId: string; rule: AlertRule | null; onDone: () => void }) {
  const queryClient = useQueryClient();
  const [type, setType] = useState<AlertRuleType>(rule?.rule_type ?? "new_seller");
  const [name, setName] = useState(rule?.name ?? RULE_TYPES.new_seller.label);
  const [severity, setSeverity] = useState<AlertSeverity | "">(rule?.severity ?? "");
  const [params, setParams] = useState<ParamValues>(() => initialParams(type, rule?.params));
  const [scopeMode, setScopeMode] = useState<ScopeMode>(
    rule?.scope.product_ids.length ? "products" : rule?.scope.brands.length ? "brands" : "all",
  );
  const [brands, setBrands] = useState(rule?.scope.brands.join(", ") ?? "");
  const [products, setProducts] = useState<Map<string, string>>(
    () => new Map((rule?.scope.product_ids ?? []).map((id) => [id, `${id.slice(0, 8)}…`])),
  );
  const [email, setEmail] = useState(rule?.channels.includes("email") ?? false);
  const [recipients, setRecipients] = useState<Set<string>>(new Set(rule?.recipient_user_ids ?? []));
  const initialIds = rule?.scope.product_ids ?? [];
  const labels = useQuery({
    queryKey: ["tenant", orgId, "products", "labels", initialIds.join(",")],
    queryFn: async () => {
      const found = await Promise.all(
        initialIds.slice(0, 50).map((id) => api<Product>(`/products/${id}`, { orgId }).catch(() => null)),
      );
      return new Map(found.flatMap((p) => (p ? [[p.id, p.external_id] as const] : [])));
    },
    enabled: initialIds.length > 0,
  });
  const members = useQuery({
    queryKey: ["tenant", orgId, "members"],
    queryFn: () => api<Member[]>("/members", { orgId }),
  });

  const save = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      rule
        ? api<AlertRule>(`/alert-rules/${rule.id}`, { method: "PATCH", orgId, body })
        : api<AlertRule>("/alert-rules", { method: "POST", orgId, body }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["tenant", orgId, "alert-rules"] });
      onDone();
    },
  });

  function changeType(next: AlertRuleType) {
    if (!rule && (name === "" || name === RULE_TYPES[type].label)) setName(RULE_TYPES[next].label);
    setType(next);
    setParams(initialParams(next));
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const body: Record<string, unknown> = {
      name,
      params: toParams(type, params),
      scope: {
        brands: scopeMode === "brands" ? brands.split(",").map((b) => b.trim()).filter(Boolean) : [],
        product_ids: scopeMode === "products" ? [...products.keys()] : [],
      },
      channels: email ? ["in_app", "email"] : ["in_app"],
      recipient_user_ids: email ? [...recipients] : [],
    };
    if (severity) body.severity = severity;
    if (!rule) body.rule_type = type;
    save.mutate(body);
  }

  const info = RULE_TYPES[type];
  const fieldErrors = save.error instanceof ApiError ? (save.error.problem.errors ?? []) : [];
  const activeMembers = (members.data ?? []).filter((m) => m.status === "active");

  return (
    <form onSubmit={submit} className="space-y-4">
      <Field label="Alert when" htmlFor="rule-type" hint={info.description}>
        <Select id="rule-type" value={type} disabled={rule !== null} onChange={(e) => changeType(e.target.value as AlertRuleType)}>
          {RULE_TYPE_ORDER.map((t) => (
            <option key={t} value={t}>
              {RULE_TYPES[t].label}
            </option>
          ))}
        </Select>
      </Field>
      {info.fields.map((f) => (
        <ParamInput
          key={`${type}-${f.key}`}
          field={f}
          value={params[f.key] ?? ""}
          onChange={(v) => setParams((prev) => ({ ...prev, [f.key]: v }))}
        />
      ))}
      <Field label="Rule name" htmlFor="rule-name">
        <Input id="rule-name" required maxLength={120} value={name} onChange={(e) => setName(e.target.value)} />
      </Field>
      <Field label="Severity" htmlFor="rule-severity">
        <Select id="rule-severity" value={severity} onChange={(e) => setSeverity(e.target.value as AlertSeverity | "")}>
          {!rule && <option value="">Default ({SEVERITY_LABELS[info.defaultSeverity]})</option>}
          {(["critical", "warning", "info"] as const).map((s) => (
            <option key={s} value={s}>
              {SEVERITY_LABELS[s]}
            </option>
          ))}
        </Select>
      </Field>

      <fieldset className="space-y-2">
        <legend className="text-sm font-medium">Products</legend>
        {(
          [
            ["all", "All products"],
            ["brands", "Products of these brands"],
            ["products", "Selected products"],
          ] as const
        ).map(([mode, label]) => (
          <label key={mode} className="mr-4 inline-flex items-center gap-2 text-sm">
            <input type="radio" name="scope" checked={scopeMode === mode} onChange={() => setScopeMode(mode)} />
            {label}
          </label>
        ))}
        {scopeMode === "brands" && (
          <Input aria-label="Brands" placeholder="Comma-separated, e.g. Acme, Globex" required value={brands} onChange={(e) => setBrands(e.target.value)} />
        )}
        {scopeMode === "products" && <ProductPicker orgId={orgId} selected={products} labels={labels.data} onChange={setProducts} />}
      </fieldset>

      <fieldset className="space-y-2">
        <legend className="text-sm font-medium">Notify</legend>
        <p className="text-xs text-[var(--text-muted)]">Alerts always appear on this page.</p>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={email} onChange={(e) => setEmail(e.target.checked)} />
          Also email these members
        </label>
        {email && (
          <ul className="space-y-1 pl-6" aria-label="Email recipients">
            {activeMembers.map((m) => (
              <li key={m.user_id}>
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={recipients.has(m.user_id)}
                    onChange={(e) => {
                      const next = new Set(recipients);
                      if (e.target.checked) next.add(m.user_id);
                      else next.delete(m.user_id);
                      setRecipients(next);
                    }}
                  />
                  {m.email}
                </label>
              </li>
            ))}
          </ul>
        )}
      </fieldset>

      {save.error && (
        <Alert>
          {errorMessage(save.error)}
          {fieldErrors.length > 1 && (
            <ul className="mt-1 list-disc pl-5">
              {fieldErrors.map((e, i) => (
                <li key={i}>{e.msg}</li>
              ))}
            </ul>
          )}
        </Alert>
      )}
      <div className="flex justify-end gap-2">
        <Button variant="secondary" onClick={onDone}>
          Cancel
        </Button>
        <Button type="submit" disabled={save.isPending}>
          {rule ? "Save rule" : "Create rule"}
        </Button>
      </div>
    </form>
  );
}

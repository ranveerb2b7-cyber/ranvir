"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { ArrowLeft, ExternalLink } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState, type FormEvent } from "react";

import { ChangeList } from "@/components/changes/change-list";
import { MockBadge } from "@/components/layout/mock-banner";
import { useSession } from "@/components/session/session-provider";
import { Alert, Button, errorMessage, Field, Input } from "@/components/ui/form";
import { Value } from "@/components/ui/value";
import { api } from "@/lib/api";
import { sellerLabel } from "@/lib/changes";
import { formatCount, formatDateTime, formatPrice } from "@/lib/format";
import { PRESENCE_LABELS, type Presence, type SellerDetail } from "@/lib/types";

const PRESENCE_STYLE: Record<Presence, string> = {
  observed: "text-green-700 dark:text-green-400",
  no_longer_observed: "text-[var(--text-muted)]",
  not_observed_inconclusive: "text-amber-700 dark:text-amber-400",
  unknown: "text-[var(--text-muted)]",
};

export default function SellerPage() {
  const { id } = useParams<{ id: string }>();
  const { org, can } = useSession();
  const queryClient = useQueryClient();
  const [notice, setNotice] = useState<string | null>(null);
  const seller = useQuery({
    queryKey: ["tenant", org.id, "sellers", "detail", id],
    queryFn: () => api<SellerDetail>(`/sellers/${id}`, { orgId: org.id }),
  });
  const save = useMutation({
    mutationFn: (body: { display_name: string; tags: string[]; notes: string }) =>
      api<SellerDetail>(`/sellers/${id}`, { method: "PATCH", orgId: org.id, body }),
    onSuccess: async () => {
      setNotice("Saved.");
      await queryClient.invalidateQueries({ queryKey: ["tenant", org.id, "sellers"] });
    },
  });

  const back = (
    <Link href="/sellers" className="text-brand-600 inline-flex items-center gap-1 text-sm">
      <ArrowLeft aria-hidden className="size-4" /> Seller Intelligence
    </Link>
  );
  if (seller.error) {
    return (
      <section className="space-y-4">
        {back}
        <Alert>{errorMessage(seller.error)}</Alert>
      </section>
    );
  }
  const s = seller.data;
  if (!s) return <p className="text-sm text-[var(--text-muted)]">Loading…</p>;

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setNotice(null);
    const form = new FormData(event.currentTarget);
    save.mutate({
      display_name: String(form.get("display_name") ?? ""),
      tags: String(form.get("tags") ?? "")
        .split(",")
        .map((t) => t.trim())
        .filter(Boolean),
      notes: String(form.get("notes") ?? ""),
    });
  }

  return (
    <section className="max-w-6xl space-y-8">
      {back}
      <div>
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-2xl font-semibold tracking-tight">{sellerLabel(s)}</h1>
          {s.is_mock && <MockBadge />}
        </div>
        <p className="mt-1 text-sm text-[var(--text-muted)]">
          Seller ID <span className="font-mono">{s.external_seller_id}</span> · first seen {formatDateTime(s.first_observed_at)} ·
          last seen {formatDateTime(s.last_observed_at)}
        </p>
        {!s.is_mock && (
          <a
            href={`https://www.amazon.in/sp?seller=${encodeURIComponent(s.external_seller_id)}`}
            target="_blank"
            rel="noopener noreferrer"
            className="text-brand-600 mt-1 inline-flex items-center gap-1 text-sm"
          >
            Open seller profile on Amazon.in <ExternalLink aria-hidden className="size-3" />
          </a>
        )}
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        <div className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-3">
          <div className="text-xs text-[var(--text-muted)]">Your products offered now</div>
          <div className="mt-1 text-xl font-semibold">{formatCount(s.products_currently_offering)}</div>
        </div>
        <div className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-3">
          <div className="text-xs text-[var(--text-muted)]">Holding the Buy Box</div>
          <div className="mt-1 text-xl font-semibold">{formatCount(s.buy_box_count)}</div>
        </div>
        <div className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-3">
          <div className="text-xs text-[var(--text-muted)]">Lowest current price</div>
          <div className="mt-1 text-xl font-semibold">
            <Value why="Not offering any of your products in the latest scans">{formatPrice(s.lowest_current_price, s.currency)}</Value>
          </div>
        </div>
      </div>

      {can("products.write") ? (
        <form onSubmit={submit} className="grid gap-4 rounded-lg border border-[var(--border)] bg-[var(--surface)] p-4 sm:grid-cols-2">
          <h2 className="font-semibold sm:col-span-2">Your labels</h2>
          {save.error && <div className="sm:col-span-2"><Alert>{errorMessage(save.error)}</Alert></div>}
          {notice && <div className="sm:col-span-2"><Alert tone="success">{notice}</Alert></div>}
          <Field label="Name" htmlFor="display_name" hint="Amazon's API doesn't provide seller names. Add the name you know.">
            <Input id="display_name" name="display_name" defaultValue={s.display_name ?? ""} maxLength={200} />
          </Field>
          <Field label="Tags" htmlFor="tags" hint="Comma-separated, e.g. authorized, unauthorized, watch">
            <Input id="tags" name="tags" defaultValue={s.tags.join(", ")} />
          </Field>
          <Field label="Notes" htmlFor="notes">
            <textarea
              id="notes"
              name="notes"
              defaultValue={s.notes ?? ""}
              maxLength={2000}
              rows={3}
              className="block w-full rounded-md border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-sm"
            />
          </Field>
          <div className="flex items-end">
            <Button type="submit" disabled={save.isPending}>Save labels</Button>
          </div>
        </form>
      ) : (
        s.notes && <p className="text-sm">Notes: {s.notes}</p>
      )}

      <div>
        <h2 className="text-lg font-semibold">Your products</h2>
        <div className="mt-3 overflow-x-auto rounded-lg border border-[var(--border)] bg-[var(--surface)]">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-[var(--border)] text-xs text-[var(--text-muted)]">
              <tr>
                <th className="px-3 py-2 font-medium">Product</th>
                <th className="px-3 py-2 font-medium">Status</th>
                <th className="px-3 py-2 text-right font-medium">Current price</th>
                <th className="px-3 py-2 font-medium">Buy Box</th>
                <th className="px-3 py-2 font-medium">Last seen</th>
              </tr>
            </thead>
            <tbody>
              {s.products.map((p) => (
                <tr key={p.product.id} className="border-b border-[var(--border)] last:border-0">
                  <td className="px-3 py-2">
                    <Link href={`/products/${p.product.id}`} className="text-brand-600 font-mono text-xs">
                      {p.product.external_id}
                    </Link>{" "}
                    {p.product.product_name}
                  </td>
                  <td className={clsx("px-3 py-2 text-xs font-medium", PRESENCE_STYLE[p.presence])}>{PRESENCE_LABELS[p.presence]}</td>
                  <td className="px-3 py-2 text-right">
                    {p.current_offer ? <Value>{formatPrice(p.current_offer.landed_price, p.current_offer.currency)}</Value> : "—"}
                  </td>
                  <td className="px-3 py-2">{p.current_offer?.is_buy_box_winner ? "Winner" : "—"}</td>
                  <td className="px-3 py-2 text-xs whitespace-nowrap">{formatDateTime(p.last_seen_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div>
        <h2 className="text-lg font-semibold">Recent changes</h2>
        <div className="mt-3">
          <ChangeList events={s.recent_changes} empty="No changes recorded for this seller yet." />
        </div>
      </div>
    </section>
  );
}

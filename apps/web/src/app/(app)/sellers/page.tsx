"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { MockBadge } from "@/components/layout/mock-banner";
import { useSession } from "@/components/session/session-provider";
import { Alert, Button, errorMessage, Input, Select } from "@/components/ui/form";
import { Value } from "@/components/ui/value";
import { api } from "@/lib/api";
import { sellerLabel } from "@/lib/changes";
import { formatCount, formatDateTime, formatPrice } from "@/lib/format";
import type { Page, SellerSummary } from "@/lib/types";

const MAX_COMPARE = 4;

export default function SellersPage() {
  const { org } = useSession();
  const router = useRouter();
  const [search, setSearch] = useState("");
  const [q, setQ] = useState("");
  const [tag, setTag] = useState("");
  const [offering, setOffering] = useState("");
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<string[]>([]);

  useEffect(() => {
    const t = setTimeout(() => {
      setQ(search.trim());
      setPage(1);
    }, 300);
    return () => clearTimeout(t);
  }, [search]);

  const params = new URLSearchParams({ page: String(page), page_size: "25" });
  if (q) params.set("q", q);
  if (tag) params.set("tag", tag);
  if (offering) params.set("currently_offering", offering);
  const sellers = useQuery({
    queryKey: ["tenant", org.id, "sellers", params.toString()],
    queryFn: () => api<Page<SellerSummary>>(`/sellers?${params.toString()}`, { orgId: org.id }),
    placeholderData: keepPreviousData,
  });
  const items = sellers.data?.items ?? [];
  const pages = Math.max(1, Math.ceil((sellers.data?.total ?? 0) / 25));

  function toggle(id: string) {
    setSelected((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : prev.length < MAX_COMPARE ? [...prev, id] : prev,
    );
  }

  return (
    <section className="max-w-6xl space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Seller Intelligence</h1>
          <p className="mt-1 text-sm text-[var(--text-muted)]">
            Sellers seen offering your products. Amazon&apos;s API identifies sellers by ID only; add your own names and
            tags (e.g. &quot;authorized&quot;, &quot;unauthorized&quot;) on each seller&apos;s page.
          </p>
        </div>
        <Button
          disabled={selected.length < 2}
          onClick={() => router.push(`/sellers/compare?${selected.map((id) => `ids=${id}`).join("&")}`)}
        >
          Compare {selected.length > 0 ? `(${selected.length})` : ""}
        </Button>
      </div>

      <div className="grid gap-3 sm:grid-cols-[1fr_200px_220px]">
        <Input aria-label="Search sellers" type="search" placeholder="Search seller ID or name" value={search} onChange={(e) => setSearch(e.target.value)} />
        <Input aria-label="Tag" placeholder="Filter by tag" value={tag} onChange={(e) => { setTag(e.target.value.trim()); setPage(1); }} />
        <Select aria-label="Currently offering" value={offering} onChange={(e) => { setOffering(e.target.value); setPage(1); }}>
          <option value="">All sellers</option>
          <option value="true">Currently offering</option>
          <option value="false">Not currently offering</option>
        </Select>
      </div>

      {sellers.error && <Alert>{errorMessage(sellers.error)}</Alert>}
      {sellers.data && items.length === 0 && (
        <p className="rounded-lg border border-dashed border-[var(--border)] bg-[var(--surface)] p-8 text-center text-sm text-[var(--text-muted)]">
          {q || tag || offering ? "No sellers match these filters." : "No sellers yet. Sellers appear after your products are scanned."}
        </p>
      )}
      {items.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-[var(--border)] bg-[var(--surface)]">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-[var(--border)] text-xs text-[var(--text-muted)]">
              <tr>
                <th className="w-8 px-3 py-2"><span className="sr-only">Compare</span></th>
                <th className="px-3 py-2 font-medium">Seller</th>
                <th className="px-3 py-2 font-medium">Tags</th>
                <th className="px-3 py-2 text-right font-medium">Your products offered</th>
                <th className="px-3 py-2 text-right font-medium">Buy Box</th>
                <th className="px-3 py-2 text-right font-medium">Lowest price</th>
                <th className="px-3 py-2 font-medium">Last seen</th>
              </tr>
            </thead>
            <tbody>
              {items.map((s) => (
                <tr key={s.id} className="border-b border-[var(--border)] last:border-0">
                  <td className="px-3 py-2">
                    <input
                      type="checkbox"
                      aria-label={`Compare ${sellerLabel(s)}`}
                      checked={selected.includes(s.id)}
                      disabled={!selected.includes(s.id) && selected.length >= MAX_COMPARE}
                      onChange={() => toggle(s.id)}
                    />
                  </td>
                  <td className="px-3 py-2">
                    <Link href={`/sellers/${s.id}`} className="text-brand-600 font-medium">
                      {sellerLabel(s)}
                    </Link>
                    {s.is_mock && <MockBadge />}
                    {s.display_name && <div className="font-mono text-xs text-[var(--text-muted)]">{s.external_seller_id}</div>}
                  </td>
                  <td className="px-3 py-2">
                    {s.tags.map((t) => (
                      <span key={t} className="mr-1 rounded bg-black/5 px-1.5 py-0.5 text-xs dark:bg-white/10">
                        {t}
                      </span>
                    ))}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">{formatCount(s.products_currently_offering)}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{formatCount(s.buy_box_count)}</td>
                  <td className="px-3 py-2 text-right">
                    <Value why="Not offering any of your products in the latest scans">{formatPrice(s.lowest_current_price, s.currency)}</Value>
                  </td>
                  <td className="px-3 py-2 text-xs whitespace-nowrap">{formatDateTime(s.last_observed_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {pages > 1 && (
        <div className="flex items-center justify-end gap-2 text-sm">
          <Button variant="secondary" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</Button>
          <span>Page {page} of {pages}</span>
          <Button variant="secondary" disabled={page >= pages} onClick={() => setPage(page + 1)}>Next</Button>
        </div>
      )}
    </section>
  );
}

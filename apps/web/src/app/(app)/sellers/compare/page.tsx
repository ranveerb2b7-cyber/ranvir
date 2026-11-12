"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { useSession } from "@/components/session/session-provider";
import { Alert, errorMessage } from "@/components/ui/form";
import { Value } from "@/components/ui/value";
import { api } from "@/lib/api";
import { sellerLabel } from "@/lib/changes";
import { formatCount, formatPrice } from "@/lib/format";
import type { SellerComparison } from "@/lib/types";

function Compare() {
  const { org } = useSession();
  const ids = useSearchParams().getAll("ids");
  const query = ids.map((id) => `ids=${encodeURIComponent(id)}`).join("&");
  const data = useQuery({
    queryKey: ["tenant", org.id, "sellers", "compare", query],
    queryFn: () => api<SellerComparison>(`/sellers/compare?${query}`, { orgId: org.id }),
    enabled: ids.length >= 2,
  });

  return (
    <section className="max-w-6xl space-y-6">
      <Link href="/sellers" className="text-brand-600 inline-flex items-center gap-1 text-sm">
        <ArrowLeft aria-hidden className="size-4" /> Seller Intelligence
      </Link>
      <h1 className="text-2xl font-semibold tracking-tight">Compare sellers</h1>
      {ids.length < 2 && <Alert>Select 2 to 4 sellers on the Seller Intelligence page.</Alert>}
      {data.error && <Alert>{errorMessage(data.error)}</Alert>}
      {data.data && (
        <div className="overflow-x-auto rounded-lg border border-[var(--border)] bg-[var(--surface)]">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-[var(--border)]">
              <tr>
                <th className="px-3 py-2 text-xs font-medium text-[var(--text-muted)]">Product (current offers)</th>
                {data.data.sellers.map((s) => (
                  <th key={s.id} className="px-3 py-2 text-right">
                    <Link href={`/sellers/${s.id}`} className="text-brand-600 font-medium">
                      {sellerLabel(s)}
                    </Link>
                    <div className="text-xs font-normal text-[var(--text-muted)]">
                      {formatCount(s.products_currently_offering)} product{s.products_currently_offering === 1 ? "" : "s"} ·{" "}
                      {formatCount(s.buy_box_count)} Buy Box
                    </div>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.data.rows.length === 0 && (
                <tr>
                  <td colSpan={data.data.sellers.length + 1} className="px-3 py-6 text-center text-[var(--text-muted)]">
                    None of these sellers offer your products in the latest scans.
                  </td>
                </tr>
              )}
              {data.data.rows.map((row) => {
                const prices = row.cells.map((c) => (c.offer?.landed_price == null ? null : Number(c.offer.landed_price)));
                const known = prices.filter((p): p is number => p !== null);
                const cheapest = known.length > 1 ? Math.min(...known) : null;
                return (
                  <tr key={row.product.id} className="border-b border-[var(--border)] last:border-0">
                    <td className="px-3 py-2">
                      <Link href={`/products/${row.product.id}`} className="text-brand-600 font-mono text-xs">
                        {row.product.external_id}
                      </Link>{" "}
                      {row.product.product_name}
                    </td>
                    {row.cells.map((c, i) => (
                      <td key={c.seller_id} className="px-3 py-2 text-right">
                        {c.offer ? (
                          <>
                            <span className={prices[i] === cheapest ? "font-semibold" : undefined}>
                              <Value>{formatPrice(c.offer.landed_price, c.offer.currency)}</Value>
                            </span>
                            {c.offer.is_buy_box_winner && <div className="text-xs text-[var(--text-muted)]">Buy Box</div>}
                            {prices[i] === cheapest && <div className="text-xs text-[var(--text-muted)]">Lowest</div>}
                          </>
                        ) : (
                          <span className="text-xs text-[var(--text-muted)]">Not offering</span>
                        )}
                      </td>
                    ))}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

export default function ComparePage() {
  return (
    <Suspense>
      <Compare />
    </Suspense>
  );
}

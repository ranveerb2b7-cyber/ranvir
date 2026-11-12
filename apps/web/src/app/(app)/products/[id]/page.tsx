"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { ArrowLeft, ExternalLink } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";

import { ChangeList } from "@/components/changes/change-list";
import { TrendChart } from "@/components/charts/trend-chart";
import { MockBadge } from "@/components/layout/mock-banner";
import { StatusBadge } from "@/components/products/products-table";
import { useSession } from "@/components/session/session-provider";
import { Alert, Button, errorMessage } from "@/components/ui/form";
import { Value } from "@/components/ui/value";
import { api } from "@/lib/api";
import { sellerLabel } from "@/lib/changes";
import { formatCount, formatDateTime, formatPrice } from "@/lib/format";
import {
  LIMITATION_LABELS,
  MOCK_SOURCE,
  type ChangeEvent,
  type OfferRow,
  type Page,
  type Product,
  type ScanJobCreated,
  type ScanSnapshot,
  type TrendPoint,
} from "@/lib/types";

const inr = (v: number) => new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 }).format(v);
const count = (v: number) => new Intl.NumberFormat("en-IN").format(v);

function Stat({ label, children, hint }: { label: string; children: React.ReactNode; hint?: string }) {
  return (
    <div className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-3" title={hint}>
      <div className="text-xs text-[var(--text-muted)]">{label}</div>
      <div className="mt-1 text-xl font-semibold">{children}</div>
    </div>
  );
}

export default function ProductDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { org, can } = useSession();
  const router = useRouter();
  const key = ["tenant", org.id, "products", "detail", id];

  const product = useQuery({ queryKey: key, queryFn: () => api<Product>(`/products/${id}`, { orgId: org.id }) });
  const offers = useQuery({
    queryKey: [...key, "offers"],
    queryFn: () => api<{ snapshot: ScanSnapshot | null; offers: OfferRow[] }>(`/products/${id}/offers`, { orgId: org.id }),
  });
  const trends = useQuery({
    queryKey: [...key, "trends"],
    queryFn: () => api<TrendPoint[]>(`/products/${id}/trends?days=90`, { orgId: org.id }),
  });
  const history = useQuery({
    queryKey: [...key, "history"],
    queryFn: () => api<Page<ChangeEvent>>(`/products/${id}/history?page_size=50`, { orgId: org.id }),
  });
  const scans = useQuery({
    queryKey: [...key, "scans"],
    queryFn: () => api<Page<ScanSnapshot>>(`/products/${id}/scans?page_size=20`, { orgId: org.id }),
  });
  const scan = useMutation({
    mutationFn: () => api<ScanJobCreated>("/scan-jobs", { method: "POST", orgId: org.id, body: { product_ids: [id] } }),
    onSuccess: (job) => router.push(`/history/${job.id}`),
  });

  const back = (
    <Link href="/products" className="text-brand-600 inline-flex items-center gap-1 text-sm">
      <ArrowLeft aria-hidden className="size-4" /> Product Mapping
    </Link>
  );
  if (product.error) {
    return (
      <section className="space-y-4">
        {back}
        <Alert>{errorMessage(product.error)}</Alert>
      </section>
    );
  }
  const p = product.data;
  if (!p) return <p className="text-sm text-[var(--text-muted)]">Loading…</p>;
  const snap = offers.data?.snapshot ?? null;
  const points = (trends.data ?? []).map((t) => ({
    t: new Date(t.retrieved_at).getTime(),
    total: t.total_offer_count,
    observed: t.observed_offer_count,
    sellers: t.unique_seller_count,
    low: t.lowest_observed_price === null ? null : Number(t.lowest_observed_price),
    high: t.highest_observed_price === null ? null : Number(t.highest_observed_price),
  }));

  return (
    <section className="max-w-6xl space-y-8">
      {back}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="font-mono text-2xl font-semibold tracking-tight">{p.external_id}</h1>
            <StatusBadge status={p.scan_status} />
            {snap?.data_source === MOCK_SOURCE && <MockBadge />}
          </div>
          <p className="mt-1 text-sm text-[var(--text-muted)]">
            {p.product_name ?? "Unnamed product"} · {p.brand_name ?? "No brand"} · Amazon.in
          </p>
          <a
            href={`https://www.amazon.in/dp/${encodeURIComponent(p.external_id)}`}
            target="_blank"
            rel="noopener noreferrer"
            className="text-brand-600 mt-1 inline-flex items-center gap-1 text-sm"
          >
            Open on Amazon.in <ExternalLink aria-hidden className="size-3" />
          </a>
        </div>
        {can("scans.run") && (
          <Button disabled={scan.isPending} onClick={() => scan.mutate()}>
            Scan now
          </Button>
        )}
      </div>
      {scan.error && <Alert>{errorMessage(scan.error)}</Alert>}

      <div>
        <h2 className="text-lg font-semibold">Latest scan</h2>
        {!snap ? (
          <p className="mt-2 text-sm text-[var(--text-muted)]">This product has not been scanned yet.</p>
        ) : (
          <>
            <p className="mt-1 text-xs text-[var(--text-muted)]">
              {formatDateTime(snap.retrieved_at)} · source: {snap.data_source}
            </p>
            <div className="mt-3 grid gap-3 sm:grid-cols-3 lg:grid-cols-5">
              <Stat label="Total offers (reported)" hint="The number of offers the marketplace says exist">
                <Value why="Not reported by the marketplace">{formatCount(snap.total_offer_count)}</Value>
              </Stat>
              <Stat label="Offers observed" hint="Offers actually received in detail">
                {formatCount(snap.observed_offer_count)}
              </Stat>
              <Stat label="Unique sellers" hint="Distinct seller IDs among observed offers">
                <Value why="Seller IDs were not provided for every offer">{formatCount(snap.unique_seller_count)}</Value>
              </Stat>
              <Stat label="Lowest price">
                <Value why="No prices observed">{formatPrice(snap.lowest_observed_price, snap.currency)}</Value>
              </Stat>
              <Stat label="Highest price">
                <Value why="No prices observed">{formatPrice(snap.highest_observed_price, snap.currency)}</Value>
              </Stat>
            </div>
            {snap.limitations.length > 0 && (
              <ul className="mt-3 space-y-1 text-xs text-[var(--text-muted)]">
                {snap.limitations.map((l) => (
                  <li key={l}>• {LIMITATION_LABELS[l] ?? l}</li>
                ))}
              </ul>
            )}
          </>
        )}
      </div>

      {offers.data && offers.data.offers.length > 0 && (
        <div>
          <h2 className="text-lg font-semibold">Offers in the latest scan</h2>
          <div className="mt-3 overflow-x-auto rounded-lg border border-[var(--border)] bg-[var(--surface)]">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-[var(--border)] text-xs text-[var(--text-muted)]">
                <tr>
                  <th className="px-3 py-2 font-medium">Seller</th>
                  <th className="px-3 py-2 text-right font-medium">Price</th>
                  <th className="px-3 py-2 text-right font-medium">Shipping</th>
                  <th className="px-3 py-2 text-right font-medium">Total</th>
                  <th className="px-3 py-2 font-medium">Fulfilled by</th>
                  <th className="px-3 py-2 font-medium">Buy Box</th>
                  <th className="px-3 py-2 text-right font-medium">Feedback</th>
                </tr>
              </thead>
              <tbody>
                {offers.data.offers.map((o) => (
                  <tr key={o.position} className="border-b border-[var(--border)] last:border-0">
                    <td className="px-3 py-2">
                      {o.seller ? (
                        <Link href={`/sellers/${o.seller.id}`} className="text-brand-600">
                          {sellerLabel(o.seller)}
                        </Link>
                      ) : (
                        <span className="text-[var(--text-muted)]">Seller not identified</span>
                      )}
                      {o.seller_tags.map((t) => (
                        <span key={t} className="ml-1 rounded bg-black/5 px-1.5 py-0.5 text-[10px] dark:bg-white/10">
                          {t}
                        </span>
                      ))}
                    </td>
                    <td className="px-3 py-2 text-right"><Value>{formatPrice(o.listing_price, o.currency)}</Value></td>
                    <td className="px-3 py-2 text-right"><Value>{formatPrice(o.shipping_price, o.currency)}</Value></td>
                    <td className="px-3 py-2 text-right font-medium"><Value>{formatPrice(o.landed_price, o.currency)}</Value></td>
                    <td className="px-3 py-2">{{ amazon: "Amazon", merchant: "Seller", unknown: "Unknown" }[o.fulfilment_channel] ?? o.fulfilment_channel}</td>
                    <td className="px-3 py-2">{o.is_buy_box_winner === null ? "Unknown" : o.is_buy_box_winner ? "Winner" : "—"}</td>
                    <td className="px-3 py-2 text-right text-xs">
                      {o.seller_feedback_rating === null ? (
                        <Value>{null}</Value>
                      ) : (
                        `${Number(o.seller_feedback_rating)}% (${formatCount(o.seller_feedback_count) ?? "?"})`
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <TrendChart
          title="Offers and sellers (90 days)"
          data={points}
          format={count}
          series={[
            { key: "total", label: "Total offers (reported)", color: "--series-1" },
            { key: "observed", label: "Offers observed", color: "--series-2" },
            { key: "sellers", label: "Unique sellers", color: "--series-3" },
          ]}
        />
        <TrendChart
          title="Observed price range (90 days)"
          data={points}
          format={inr}
          zeroBaseline={false}
          series={[
            { key: "low", label: "Lowest price", color: "--series-1" },
            { key: "high", label: "Highest price", color: "--series-2" },
          ]}
        />
      </div>

      <div>
        <h2 className="text-lg font-semibold">Changes</h2>
        <p className="mt-1 mb-3 text-xs text-[var(--text-muted)]">
          Detected by comparing each scan with the previous usable one. A seller missing from an incomplete offer list is
          never reported as gone.
        </p>
        <ChangeList events={history.data?.items ?? []} showProduct={false} empty="No changes detected yet. The first scan is the baseline." />
      </div>

      <div>
        <h2 className="text-lg font-semibold">Scan history</h2>
        <div className="mt-3 overflow-x-auto rounded-lg border border-[var(--border)] bg-[var(--surface)]">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-[var(--border)] text-xs text-[var(--text-muted)]">
              <tr>
                <th className="px-3 py-2 font-medium">Scanned</th>
                <th className="px-3 py-2 font-medium">Result</th>
                <th className="px-3 py-2 text-right font-medium">Total offers</th>
                <th className="px-3 py-2 text-right font-medium">Observed</th>
                <th className="px-3 py-2 text-right font-medium">Sellers</th>
                <th className="px-3 py-2 font-medium">Source</th>
              </tr>
            </thead>
            <tbody>
              {scans.data?.items.map((s) => (
                <tr key={s.id} className="border-b border-[var(--border)] last:border-0">
                  <td className="px-3 py-2 whitespace-nowrap">{formatDateTime(s.retrieved_at)}</td>
                  <td className="px-3 py-2">
                    {s.status === "error" ? (
                      <span className="text-red-700 dark:text-red-400">Failed ({s.error_code})</span>
                    ) : (
                      s.status
                    )}
                  </td>
                  <td className="px-3 py-2 text-right"><Value>{formatCount(s.total_offer_count)}</Value></td>
                  <td className="px-3 py-2 text-right">{s.status === "error" ? "—" : formatCount(s.observed_offer_count)}</td>
                  <td className="px-3 py-2 text-right"><Value>{formatCount(s.unique_seller_count)}</Value></td>
                  <td className="px-3 py-2 text-xs">{s.data_source}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}

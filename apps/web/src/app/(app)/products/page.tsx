"use client";

import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { Plus, ScanSearch } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { AddProductDialog, EditProductDialog } from "@/components/products/product-dialogs";
import {
  COLUMNS,
  OfferCount,
  Price,
  SellerCount,
  SortHeader,
  StatusBadge,
  type SortKey,
} from "@/components/products/products-table";
import { useSession } from "@/components/session/session-provider";
import { Alert, Button, errorMessage, Input, Select } from "@/components/ui/form";
import { Value } from "@/components/ui/value";
import { api } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import {
  SCAN_STATUS_LABELS,
  type BrandCount,
  type Product,
  type ProductPage,
  type ScanJobCreated,
  type ScanStatus,
} from "@/lib/types";

const PAGE_SIZES = [25, 50, 100];
const NO_BRAND = "__none__";

function ProductsView() {
  const { org, can } = useSession();
  const canWrite = can("products.write");
  const canScan = can("scans.run");
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const queryClient = useQueryClient();

  const q = params.get("q") ?? "";
  const brand = params.get("brand") ?? "";
  const status = (params.get("status") ?? "") as ScanStatus | "";
  const multi = params.get("multi") ?? "";
  const sort = (params.get("sort") ?? "created_at") as SortKey;
  const order = (params.get("order") ?? "desc") as "asc" | "desc";
  const page = Math.max(1, Number(params.get("page") ?? 1) || 1);
  const pageSize = PAGE_SIZES.includes(Number(params.get("size"))) ? Number(params.get("size")) : 25;

  function setParams(changes: Record<string, string | number | null>, resetPage = true) {
    // Read the live URL, not a value captured at render time: the debounced search update can
    // fire after other filters changed, and must not restore their old values.
    const next = new URLSearchParams(window.location.search);
    for (const [k, v] of Object.entries(changes)) {
      if (v === null || v === "") next.delete(k);
      else next.set(k, String(v));
    }
    if (resetPage) next.delete("page");
    router.replace(`${pathname}?${next.toString()}`, { scroll: false });
  }

  // Search box: local state, pushed to the URL after typing pauses.
  const [search, setSearch] = useState(q);
  useEffect(() => {
    if (search === q) return;
    const t = setTimeout(() => setParams({ q: search.trim() || null }), 300);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  const query = new URLSearchParams({ sort, order, page: String(page), page_size: String(pageSize) });
  if (q) query.set("q", q);
  if (brand) query.set("brand", brand);
  if (status) query.set("scan_status", status);
  if (multi) query.set("multiple_sellers", multi);

  const products = useQuery({
    queryKey: ["tenant", org.id, "products", query.toString()],
    queryFn: () => api<ProductPage>(`/products?${query.toString()}`, { orgId: org.id }),
    placeholderData: keepPreviousData,
  });
  const brands = useQuery({
    queryKey: ["tenant", org.id, "brands"],
    queryFn: () => api<BrandCount[]>("/brands", { orgId: org.id }),
  });

  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<Product | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [bulkError, setBulkError] = useState<string | null>(null);
  const [scanning, setScanning] = useState(false);

  async function scan(body: { product_ids: string[] } | { all_monitored: true }) {
    setScanning(true);
    setBulkError(null);
    try {
      const job = await api<ScanJobCreated>("/scan-jobs", { method: "POST", orgId: org.id, body });
      await queryClient.invalidateQueries({ queryKey: ["tenant", org.id, "scan-jobs"] });
      router.push(`/history/${job.id}`);
    } catch (e) {
      setBulkError(errorMessage(e));
      setScanning(false);
    }
  }
  const [notice, setNotice] = useState<string | null>(null);

  const items = products.data?.items ?? [];
  const total = products.data?.total ?? 0;
  // Describe the rows actually on screen (the previous page stays visible while the next loads).
  const shownPage = products.data?.page ?? page;
  const shownSize = products.data?.page_size ?? pageSize;
  const pages = Math.max(1, Math.ceil(total / shownSize));
  const loadingNext = products.isPlaceholderData;
  const visibleSelected = items.filter((p) => selected.has(p.id));
  const allSelected = items.length > 0 && visibleSelected.length === items.length;
  const filtered = Boolean(q || brand || status || multi);

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function bulk(action: "delete" | "enable_monitoring" | "disable_monitoring" | "set_brand") {
    const ids = [...selected];
    let brandName: string | null = null;
    if (action === "set_brand") {
      brandName = window.prompt(`Brand for ${ids.length} product(s) (leave empty to clear):`);
      if (brandName === null) return;
    }
    if (action === "delete" && !window.confirm(`Delete ${ids.length} product(s)? Their scan history is kept.`)) return;
    setBulkError(null);
    try {
      const result = await api<{ affected: number }>("/products/bulk", {
        method: "POST",
        orgId: org.id,
        body: action === "set_brand" ? { ids, action, brand_name: brandName } : { ids, action },
      });
      setNotice(`Updated ${result.affected} product(s).`);
      setSelected(new Set());
      await queryClient.invalidateQueries({ queryKey: ["tenant", org.id] });
    } catch (e) {
      setBulkError(errorMessage(e));
    }
  }

  function onSort(key: SortKey) {
    if (key === sort) setParams({ order: order === "asc" ? "desc" : "asc" });
    else setParams({ sort: key, order: key === "created_at" || key === "last_scanned_at" ? "desc" : "asc" });
  }

  return (
    <section className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Product Mapping</h1>
          <p className="mt-1 text-sm text-[var(--text-muted)]">
            Amazon.in products you monitor. Offer, seller and price data appear after the first scan.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {canScan && total > 0 && (
            <Button variant="secondary" disabled={scanning} onClick={() => void scan({ all_monitored: true })}>
              <ScanSearch aria-hidden className="mr-1 size-4" />
              Scan all monitored
            </Button>
          )}
          {canWrite && (
            <Button onClick={() => setAdding(true)}>
              <Plus aria-hidden className="mr-1 size-4" />
              Add product
            </Button>
          )}
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-[1fr_200px_180px_180px]">
        <Input
          aria-label="Search products"
          type="search"
          placeholder="Search ASIN, name or brand"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <Select aria-label="Brand" value={brand} onChange={(e) => setParams({ brand: e.target.value })}>
          <option value="">All brands</option>
          {brands.data?.map((b) => (
            <option key={b.brand_name ?? NO_BRAND} value={b.brand_name ?? NO_BRAND}>
              {b.brand_name ?? "No brand"} ({b.products})
            </option>
          ))}
        </Select>
        <Select aria-label="Scan status" value={status} onChange={(e) => setParams({ status: e.target.value })}>
          <option value="">Any scan status</option>
          {(Object.keys(SCAN_STATUS_LABELS) as ScanStatus[]).map((s) => (
            <option key={s} value={s}>
              {SCAN_STATUS_LABELS[s]}
            </option>
          ))}
        </Select>
        <Select aria-label="Sellers" value={multi} onChange={(e) => setParams({ multi: e.target.value })}>
          <option value="">Any number of sellers</option>
          <option value="true">Multiple sellers</option>
          <option value="false">Single seller</option>
        </Select>
      </div>

      {notice && <Alert tone="success">{notice}</Alert>}
      {bulkError && <Alert>{bulkError}</Alert>}
      {products.error && <Alert>{errorMessage(products.error)}</Alert>}

      {canWrite && visibleSelected.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-[var(--border)] bg-[var(--surface)] p-3 text-sm">
          <span className="mr-2 font-medium">{selected.size} selected</span>
          {canScan && (
            <Button disabled={scanning} onClick={() => void scan({ product_ids: [...selected] })}>
              Scan now
            </Button>
          )}
          <Button variant="secondary" onClick={() => void bulk("set_brand")}>
            Set brand
          </Button>
          <Button variant="secondary" onClick={() => void bulk("enable_monitoring")}>
            Monitor
          </Button>
          <Button variant="secondary" onClick={() => void bulk("disable_monitoring")}>
            Stop monitoring
          </Button>
          <Button variant="danger" onClick={() => void bulk("delete")}>
            Delete
          </Button>
        </div>
      )}

      {products.isPending ? (
        <p className="text-sm text-[var(--text-muted)]">Loading…</p>
      ) : items.length === 0 ? (
        <div className="rounded-lg border border-dashed border-[var(--border)] bg-[var(--surface)] p-8 text-center text-sm text-[var(--text-muted)]">
          {filtered ? "No products match these filters." : "No products yet. Add an ASIN to start monitoring."}
        </div>
      ) : (
        <>
          {/* Desktop table */}
          <div
            aria-busy={loadingNext}
            className={clsx(
              "hidden overflow-x-auto rounded-lg border border-[var(--border)] bg-[var(--surface)] transition-opacity md:block",
              loadingNext && "opacity-50",
            )}
          >
            <table className="w-full text-left text-sm">
              <thead className="border-b border-[var(--border)] text-xs text-[var(--text-muted)]">
                <tr>
                  {canWrite && (
                    <th className="w-8 px-3 py-2">
                      <input
                        type="checkbox"
                        aria-label="Select all on this page"
                        checked={allSelected}
                        onChange={() =>
                          setSelected((prev) => {
                            const next = new Set(prev);
                            for (const p of items) {
                              if (allSelected) next.delete(p.id);
                              else next.add(p.id);
                            }
                            return next;
                          })
                        }
                      />
                    </th>
                  )}
                  {COLUMNS.map((c) => (
                    <th
                      key={c.key}
                      scope="col"
                      aria-sort={c.sort === sort ? (order === "asc" ? "ascending" : "descending") : undefined}
                      className={clsx("px-3 py-2 font-medium whitespace-nowrap", c.numeric && "text-right")}
                    >
                      <SortHeader column={c} sort={sort} order={order} onSort={onSort} />
                    </th>
                  ))}
                  {canWrite && <th className="px-3 py-2" />}
                </tr>
              </thead>
              <tbody>
                {items.map((p) => (
                  <tr key={p.id} className={clsx("border-b border-[var(--border)] last:border-0", !p.monitoring_enabled && "opacity-60")}>
                    {canWrite && (
                      <td className="px-3 py-2">
                        <input
                          type="checkbox"
                          aria-label={`Select ${p.external_id}`}
                          checked={selected.has(p.id)}
                          onChange={() => toggle(p.id)}
                        />
                      </td>
                    )}
                    {COLUMNS.map((c) => (
                      <td key={c.key} className={clsx("px-3 py-2 align-top", c.numeric && "text-right")}>
                        {c.render(p)}
                      </td>
                    ))}
                    {canWrite && (
                      <td className="px-3 py-2 text-right">
                        <button type="button" className="text-brand-600 text-xs hover:underline" onClick={() => setEditing(p)}>
                          Edit<span className="sr-only"> {p.external_id}</span>
                        </button>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Mobile cards */}
          <ul className="space-y-3 md:hidden">
            {items.map((p) => (
              <li key={p.id} className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-4 text-sm">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <Link href={`/products/${p.id}`} className="text-brand-600 font-mono text-xs">
                      {p.external_id}
                    </Link>
                    <div className="truncate font-medium">{p.product_name ?? "Unnamed product"}</div>
                    <div className="text-xs text-[var(--text-muted)]">{p.brand_name ?? "No brand"}</div>
                  </div>
                  <StatusBadge status={p.scan_status} />
                </div>
                <dl className="mt-3 grid grid-cols-2 gap-2 text-xs">
                  <div><dt className="text-[var(--text-muted)]">Offers</dt><dd><OfferCount product={p} /></dd></div>
                  <div><dt className="text-[var(--text-muted)]">Unique sellers</dt><dd><SellerCount product={p} /></dd></div>
                  <div><dt className="text-[var(--text-muted)]">Lowest price</dt><dd><Price product={p} which="lowest" /></dd></div>
                  <div><dt className="text-[var(--text-muted)]">Highest price</dt><dd><Price product={p} which="highest" /></dd></div>
                  <div className="col-span-2">
                    <dt className="text-[var(--text-muted)]">Last scanned</dt>
                    <dd><Value>{formatDateTime(p.last_scanned_at)}</Value></dd>
                  </div>
                </dl>
                {canWrite && (
                  <div className="mt-3 flex justify-between">
                    <label className="flex items-center gap-2 text-xs">
                      <input type="checkbox" checked={selected.has(p.id)} onChange={() => toggle(p.id)} />
                      Select
                    </label>
                    <button type="button" className="text-brand-600 text-xs" onClick={() => setEditing(p)}>
                      Edit
                    </button>
                  </div>
                )}
              </li>
            ))}
          </ul>

          <nav aria-label="Pagination" className="flex flex-wrap items-center justify-between gap-3 text-sm">
            <span className="text-[var(--text-muted)]">
              {(shownPage - 1) * shownSize + 1}–{Math.min(shownPage * shownSize, total)} of {total}
            </span>
            <div className="flex items-center gap-2">
              <Select
                aria-label="Rows per page"
                value={pageSize}
                onChange={(e) => setParams({ size: e.target.value })}
                className="w-32!"
              >
                {PAGE_SIZES.map((s) => (
                  <option key={s} value={s}>
                    {s} / page
                  </option>
                ))}
              </Select>
              <Button variant="secondary" disabled={loadingNext || shownPage <= 1} onClick={() => setParams({ page: shownPage - 1 }, false)}>
                Previous
              </Button>
              <span>
                Page {shownPage} of {pages}
              </span>
              <Button variant="secondary" disabled={loadingNext || shownPage >= pages} onClick={() => setParams({ page: shownPage + 1 }, false)}>
                Next
              </Button>
            </div>
          </nav>
        </>
      )}

      <AddProductDialog
        orgId={org.id}
        open={adding}
        onClose={() => setAdding(false)}
      />
      <EditProductDialog orgId={org.id} product={editing} onClose={() => setEditing(null)} />
    </section>
  );
}

export default function ProductsPage() {
  return (
    <Suspense>
      <ProductsView />
    </Suspense>
  );
}

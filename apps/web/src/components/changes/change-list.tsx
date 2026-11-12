import clsx from "clsx";
import Link from "next/link";

import { CONFIDENCE_LABELS, describeChange } from "@/lib/changes";
import { formatDateTime } from "@/lib/format";
import type { ChangeEvent } from "@/lib/types";

const DOT: Record<string, string> = {
  seller_newly_observed: "bg-[var(--series-1)]",
  seller_no_longer_observed: "bg-[var(--series-2)]",
  seller_not_observed_inconclusive: "bg-transparent border border-[var(--text-muted)]",
  price_changed: "bg-[var(--series-3)]",
};

export function ChangeList({ events, showProduct = true, empty }: {
  events: ChangeEvent[];
  showProduct?: boolean;
  empty: string;
}) {
  if (events.length === 0) return <p className="text-sm text-[var(--text-muted)]">{empty}</p>;
  return (
    <ol className="divide-y divide-[var(--border)] rounded-lg border border-[var(--border)] bg-[var(--surface)]">
      {events.map((e) => (
        <li key={e.id} className="flex gap-3 px-4 py-3 text-sm">
          <span aria-hidden className={clsx("mt-1.5 size-2 shrink-0 rounded-full", DOT[e.event_type] ?? "bg-[var(--text-muted)]")} />
          <div className="min-w-0 flex-1">
            <p className={clsx(e.confidence === "low" && "text-[var(--text-muted)]")}>{describeChange(e)}</p>
            <p className="mt-0.5 text-xs text-[var(--text-muted)]">
              {formatDateTime(e.created_at)}
              {showProduct && (
                <>
                  {" · "}
                  <Link href={`/products/${e.product.id}`} className="text-brand-600 font-mono">
                    {e.product.external_id}
                  </Link>
                  {e.product.product_name && ` ${e.product.product_name}`}
                </>
              )}
              {e.seller && (
                <>
                  {" · "}
                  <Link href={`/sellers/${e.seller.id}`} className="text-brand-600">
                    seller details
                  </Link>
                </>
              )}
              {e.confidence && ` · ${CONFIDENCE_LABELS[e.confidence]}`}
            </p>
          </div>
        </li>
      ))}
    </ol>
  );
}

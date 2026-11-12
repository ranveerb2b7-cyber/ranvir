import type { ChangeEvent } from "@/lib/types";

/** Display name for a seller: your label if set, else the marketplace seller ID. */
export function sellerLabel(seller: { display_name: string | null; external_seller_id: string } | null): string {
  if (!seller) return "Unknown seller";
  return seller.display_name ?? seller.external_seller_id;
}

function price(v: Record<string, string | number | null> | null): string {
  if (!v || v.price == null) return "?";
  const amount = Number(v.price);
  return new Intl.NumberFormat("en-IN", { style: "currency", currency: String(v.currency ?? "INR") }).format(amount);
}

/** One plain-language sentence per change event. */
export function describeChange(e: ChangeEvent): string {
  const who = sellerLabel(e.seller);
  switch (e.event_type) {
    case "seller_newly_observed":
      return `New seller: ${who} started offering this product.`;
    case "seller_no_longer_observed":
      return `${who} is no longer offering this product.`;
    case "seller_not_observed_inconclusive":
      return `${who} was not in the latest offer list, but the list was incomplete, so they may still be selling.`;
    case "offer_count_changed":
      return `Total offers changed from ${e.old_value?.total_offer_count} to ${e.new_value?.total_offer_count}.`;
    case "price_changed":
      return `${who} changed price from ${price(e.old_value)} to ${price(e.new_value)}.`;
    case "buy_box_changed":
      return `Buy Box moved to ${who}.`;
    case "scan_unavailable":
      return "The marketplace stopped providing offer data for this product.";
    default:
      return e.event_type;
  }
}

export const CONFIDENCE_LABELS = { high: "High confidence", medium: "Medium confidence", low: "Low confidence" } as const;

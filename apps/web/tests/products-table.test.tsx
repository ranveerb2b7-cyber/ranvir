import { render, screen } from "@testing-library/react";

import { OfferCount, Price, SellerCount, StatusBadge } from "@/components/products/products-table";
import { formatPrice, reasonText } from "@/lib/format";
import type { LatestScan, Product } from "@/lib/types";

function product(scan: Partial<LatestScan> | null): Product {
  return {
    id: "p1",
    marketplace: "amazon_in",
    external_id: "B0CHX1W1XY",
    product_name: "Bottle",
    brand_name: "Hydra",
    identifier_status: "format_valid",
    monitoring_enabled: true,
    created_at: "2026-11-01T00:00:00Z",
    last_scanned_at: scan ? "2026-11-02T00:00:00Z" : null,
    scan_status: scan ? (scan.status ?? "ok") : "not_scanned",
    latest_scan: scan
      ? {
          status: "ok",
          data_source: "test",
          retrieved_at: "2026-11-02T00:00:00Z",
          total_offer_count: null,
          observed_offer_count: 0,
          unique_seller_count: null,
          is_offer_list_truncated: null,
          lowest_observed_price: null,
          highest_observed_price: null,
          currency: null,
          limitations: [],
          ...scan,
        }
      : null,
  };
}

describe("product cells never show 0 for unknown values", () => {
  it("unscanned product: everything Not available", () => {
    const p = product(null);
    render(
      <>
        <OfferCount product={p} />
        <SellerCount product={p} />
        <Price product={p} which="lowest" />
        <StatusBadge status={p.scan_status} />
      </>,
    );
    expect(screen.getAllByText("Not available")).toHaveLength(3);
    expect(screen.getByText("Not scanned yet")).toBeInTheDocument();
    expect(screen.queryByText("0")).not.toBeInTheDocument();
  });

  it("unknown seller count stays unknown even when offers were observed", () => {
    const p = product({ status: "partial", total_offer_count: 7, observed_offer_count: 2, unique_seller_count: null });
    render(
      <>
        <OfferCount product={p} />
        <SellerCount product={p} />
      </>,
    );
    expect(screen.getByText("7")).toBeInTheDocument();
    expect(screen.getByText("2 observed")).toBeInTheDocument();
    expect(screen.getByText("Not available")).toBeInTheDocument();
  });

  it("shows real zeros and real prices", () => {
    const p = product({
      total_offer_count: 0,
      observed_offer_count: 0,
      unique_seller_count: 0,
      lowest_observed_price: "1999.50",
      currency: "INR",
    });
    render(
      <>
        <OfferCount product={p} />
        <SellerCount product={p} />
        <Price product={p} which="lowest" />
      </>,
    );
    expect(screen.getAllByText("0")).toHaveLength(2);
    expect(screen.getByText("₹1,999.50")).toBeInTheDocument();
  });
});

describe("format helpers", () => {
  it("formatPrice needs both value and currency", () => {
    expect(formatPrice("150.00", "INR")).toBe("₹150.00");
    expect(formatPrice("150.00", null)).toBeNull();
    expect(formatPrice(null, "INR")).toBeNull();
    expect(formatPrice("abc", "INR")).toBeNull();
  });
  it("reasonText explains reason codes", () => {
    expect(reasonText("no_scans_yet")).toBe("No scans have run yet.");
    expect(reasonText(null)).toBeUndefined();
  });
});

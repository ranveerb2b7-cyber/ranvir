import { fireEvent, render, screen } from "@testing-library/react";

import { TrendChart } from "@/components/charts/trend-chart";
import { describeChange, sellerLabel } from "@/lib/changes";
import type { ChangeEvent } from "@/lib/types";

function event(event_type: string, extra: Partial<ChangeEvent> = {}): ChangeEvent {
  return {
    id: "e1",
    created_at: "2026-11-12T10:00:00Z",
    event_type,
    confidence: "high",
    product: { id: "p1", external_id: "B0CHX1W1XY", product_name: null, brand_name: null },
    seller: { id: "s1", external_seller_id: "A1SELLER", display_name: null },
    old_value: null,
    new_value: null,
    scan_result_id: "r2",
    previous_scan_result_id: "r1",
    ...extra,
  };
}

describe("change descriptions", () => {
  it("names sellers by your label, else their marketplace ID", () => {
    expect(sellerLabel({ display_name: null, external_seller_id: "A1SELLER" })).toBe("A1SELLER");
    expect(sellerLabel({ display_name: "Blue Traders", external_seller_id: "A1SELLER" })).toBe("Blue Traders");
  });

  it("never calls an inconclusive absence a departure", () => {
    const text = describeChange(event("seller_not_observed_inconclusive", { confidence: "low" }));
    expect(text).toMatch(/may still be selling/);
    expect(text).not.toMatch(/no longer/);
  });

  it("formats price changes in rupees", () => {
    const text = describeChange(
      event("price_changed", {
        old_value: { seller_id: "A1SELLER", price: "1999.00", currency: "INR" },
        new_value: { seller_id: "A1SELLER", price: "1799.50", currency: "INR" },
      }),
    );
    expect(text).toBe("A1SELLER changed price from ₹1,999.00 to ₹1,799.50.");
  });
});

describe("TrendChart", () => {
  it("shows unknown values as Not available in the table view, never 0", () => {
    render(
      <TrendChart
        title="Offers"
        format={(v) => String(v)}
        series={[{ key: "sellers", label: "Unique sellers", color: "--series-1" }]}
        data={[
          { t: Date.parse("2026-11-01T00:00:00Z"), sellers: 3 },
          { t: Date.parse("2026-11-02T00:00:00Z"), sellers: null },
        ]}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Show as table" }));
    expect(screen.getByText("3")).toBeInTheDocument();
    expect(screen.getByText("Not available")).toBeInTheDocument();
    expect(screen.queryByText("0")).not.toBeInTheDocument();
  });

  it("asks for two scans before drawing a trend", () => {
    render(<TrendChart title="Offers" format={String} series={[]} data={[{ t: 1 }]} />);
    expect(screen.getByText("A trend appears after at least two successful scans.")).toBeInTheDocument();
  });
});

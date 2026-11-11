import { render, screen } from "@testing-library/react";

import { MetricTile } from "@/components/ui/metric-tile";

describe("MetricTile", () => {
  it("renders 'Not available' (never 0) when value is null", () => {
    render(<MetricTile label="Offers" value={null} unavailableReason="No scans yet." />);
    expect(screen.getByText("Not available")).toBeInTheDocument();
    expect(screen.getByText("No scans yet.")).toBeInTheDocument();
    expect(screen.queryByText("0")).not.toBeInTheDocument();
  });

  it("renders a real zero as 0", () => {
    render(<MetricTile label="Offers" value={0} />);
    expect(screen.getByText("0")).toBeInTheDocument();
  });

  it("formats numbers for en-IN", () => {
    render(<MetricTile label="Offers" value={1234567} />);
    expect(screen.getByText("12,34,567")).toBeInTheDocument();
  });
});

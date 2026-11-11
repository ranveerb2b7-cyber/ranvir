import { NAV_ITEMS, navItem } from "@/lib/navigation";

describe("navigation", () => {
  it("contains the 9 sections from the product spec, in order", () => {
    expect(NAV_ITEMS.map((n) => n.label)).toEqual([
      "Dashboard",
      "Upload Products",
      "Product Mapping",
      "Seller Intelligence",
      "Scan History",
      "Alerts",
      "Reports",
      "Team Management",
      "Settings",
    ]);
  });

  it("throws for unknown routes", () => {
    expect(() => navItem("/nope")).toThrow();
  });
});

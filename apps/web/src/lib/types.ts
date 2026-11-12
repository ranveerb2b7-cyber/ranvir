/** API response types (mirrors apps/api/src/sellerscope/schemas/accounts.py). */
export type Role = "owner" | "admin" | "analyst" | "viewer";
export type AssignableRole = Exclude<Role, "owner">;

export interface Membership {
  organization_id: string;
  organization_name: string;
  organization_slug: string;
  role: Role;
}

export interface Me {
  id: string;
  email: string;
  full_name: string | null;
  memberships: Membership[];
}

export interface Organization {
  id: string;
  name: string;
  slug: string;
  role: Role;
  permissions: string[];
  created_at: string;
}

export interface Member {
  user_id: string;
  email: string;
  full_name: string | null;
  role: Role;
  status: "active" | "suspended";
  joined_at: string;
}

export interface Invitation {
  id: string;
  email: string;
  role: AssignableRole;
  expires_at: string;
  created_at: string;
  invited_by: string | null;
}

export interface InvitationSent extends Invitation {
  email_sent: boolean;
}

export interface InvitationPreview {
  organization_name: string;
  email: string;
  role: AssignableRole;
  status: "pending" | "accepted" | "revoked" | "expired";
  email_matches: boolean;
}

export const ROLE_LABELS: Record<Role, string> = {
  owner: "Owner",
  admin: "Admin",
  analyst: "Analyst",
  viewer: "Viewer",
};

// ---- Products & dashboard (mirrors apps/api/src/sellerscope/schemas/products.py) ----

export type ScanStatus = "not_scanned" | "ok" | "partial" | "not_found" | "unavailable" | "error";

export interface LatestScan {
  status: Exclude<ScanStatus, "not_scanned">;
  data_source: string;
  retrieved_at: string;
  /** Marketplace-reported number of offers. Null when unknown. */
  total_offer_count: number | null;
  /** Offers actually received. */
  observed_offer_count: number;
  /** Distinct seller ids among observed offers. Null when the source gave no seller ids. */
  unique_seller_count: number | null;
  is_offer_list_truncated: boolean | null;
  /** Decimal strings, e.g. "199.00". */
  lowest_observed_price: string | null;
  highest_observed_price: string | null;
  currency: string | null;
  limitations: string[];
}

export interface Product {
  id: string;
  marketplace: string;
  external_id: string;
  product_name: string | null;
  brand_name: string | null;
  identifier_status: string;
  monitoring_enabled: boolean;
  created_at: string;
  last_scanned_at: string | null;
  scan_status: ScanStatus;
  latest_scan: LatestScan | null;
}

export interface ProductPage {
  items: Product[];
  total: number;
  page: number;
  page_size: number;
}

export interface IdentifierCheck {
  input: string;
  normalized: string | null;
  valid: boolean;
  error: string | null;
  message: string | null;
  warnings: string[];
  warning_messages: string[];
  existing_product_id: string | null;
}

export interface BrandCount {
  brand_name: string | null;
  products: number;
}

export interface Metric {
  value: number | null;
  reason: string | null;
}

export interface DashboardSummary {
  total_products_monitored: Metric;
  products_successfully_scanned: Metric;
  products_with_multiple_sellers: Metric;
  total_offers_observed: Metric;
  new_sellers_detected_7d: Metric;
  products_with_unavailable_data: Metric;
  last_scan_at: string | null;
  marketplaces: {
    marketplace: string;
    name: string;
    products: number;
    scanned: number;
    with_multiple_sellers: Metric;
    total_offers_observed: Metric;
  }[];
}

export const MARKETPLACE_LABELS: Record<string, string> = { amazon_in: "Amazon.in" };

export const SCAN_STATUS_LABELS: Record<ScanStatus, string> = {
  not_scanned: "Not scanned yet",
  ok: "Scanned",
  partial: "Partial data",
  not_found: "Not found",
  unavailable: "Unavailable",
  error: "Failed",
};

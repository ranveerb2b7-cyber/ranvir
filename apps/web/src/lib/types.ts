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
  open_alerts: Metric;
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

// ---- Uploads (mirrors apps/api/src/sellerscope/schemas/uploads.py) ----

export type BatchStatus = "uploaded" | "parsing" | "preview_ready" | "committed" | "failed" | "discarded";
export type RowStatus = "valid" | "invalid" | "duplicate_in_file" | "duplicate_existing";

export interface Batch {
  id: string;
  original_filename: string;
  file_size_bytes: number;
  status: BatchStatus;
  total_rows: number;
  valid_rows: number;
  invalid_rows: number;
  duplicate_in_file_rows: number;
  duplicate_existing_rows: number;
  committed_rows: number;
  column_mapping: Record<string, string> | null;
  error_code: string | null;
  error_message: string | null;
  uploaded_by: string | null;
  created_at: string;
  parsed_at: string | null;
  committed_at: string | null;
}

export interface BatchDetail extends Batch {
  plan: { limit: number | null; current: number; remaining: number | null };
  same_file_as: string | null;
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface RowIssue {
  code: string;
  message: string;
}

export interface BatchRow {
  row_number: number;
  status: RowStatus;
  asin: string | null;
  product_name: string | null;
  brand_name: string | null;
  original: Record<string, string>;
  errors: RowIssue[];
  warnings: RowIssue[];
  product_id: string | null;
}

export const BATCH_STATUS_LABELS: Record<BatchStatus, string> = {
  uploaded: "Queued",
  parsing: "Processing",
  preview_ready: "Ready to review",
  committed: "Added",
  failed: "Failed",
  discarded: "Discarded",
};

export const ROW_STATUS_LABELS: Record<RowStatus, string> = {
  valid: "Ready to add",
  invalid: "Invalid",
  duplicate_in_file: "Duplicate in file",
  duplicate_existing: "Already in products",
};

// ---- Scans (mirrors apps/api/src/sellerscope/schemas/scans.py) ----

export type JobStatus = "queued" | "running" | "completed" | "completed_with_errors" | "failed" | "cancelled";
export type ItemStatus = "pending" | "processing" | "completed" | "partial" | "unavailable" | "failed" | "cancelled";

export interface ScanJob {
  id: string;
  trigger: "manual" | "scheduled" | "extension" | "api";
  status: JobStatus;
  total_items: number;
  completed_items: number;
  failed_items: number;
  unavailable_items: number;
  cancelled_items: number;
  requested_by: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  cancel_requested_at: string | null;
}

export interface ScanJobCreated extends ScanJob {
  already_running: string[];
  not_found: string[];
}

export interface ScanItem {
  product_id: string;
  external_id: string;
  product_name: string | null;
  status: ItemStatus;
  attempt_count: number;
  next_attempt_at: string | null;
  last_error_code: string | null;
  last_error_message: string | null;
  started_at: string | null;
  finished_at: string | null;
  result: {
    status: string;
    data_source: string;
    total_offer_count: number | null;
    observed_offer_count: number;
    unique_seller_count: number | null;
    lowest_observed_price: string | null;
    highest_observed_price: string | null;
    currency: string | null;
    limitations: string[];
    error_code: string | null;
  } | null;
}

export interface ScanQuota {
  limit: number | null;
  used: number;
  remaining: number | null;
  period_start: string;
}

export interface Meta {
  environment: string;
  version: string;
  mock_connector_enabled: boolean;
}

export const JOB_STATUS_LABELS: Record<JobStatus, string> = {
  queued: "Queued",
  running: "Running",
  completed: "Completed",
  completed_with_errors: "Completed with issues",
  failed: "Failed",
  cancelled: "Cancelled",
};

export const ITEM_STATUS_LABELS: Record<ItemStatus, string> = {
  pending: "Waiting",
  processing: "Scanning",
  completed: "Done",
  partial: "Done (partial data)",
  unavailable: "Data unavailable",
  failed: "Failed",
  cancelled: "Cancelled",
};

export const ACTIVE_JOB: JobStatus[] = ["queued", "running"];
export const MOCK_SOURCE = "MOCK";

// ---- Seller intelligence & history (mirrors apps/api/src/sellerscope/schemas/intel.py) ----

export type Presence = "observed" | "no_longer_observed" | "not_observed_inconclusive" | "unknown";

export interface SellerRef {
  id: string;
  external_seller_id: string;
  display_name: string | null;
}

export interface ProductRef {
  id: string;
  external_id: string;
  product_name: string | null;
  brand_name: string | null;
}

export interface SellerSummary {
  id: string;
  external_seller_id: string;
  display_name: string | null;
  display_name_source: string | null;
  tags: string[];
  first_observed_at: string;
  last_observed_at: string;
  products_currently_offering: number;
  buy_box_count: number;
  lowest_current_price: string | null;
  currency: string | null;
  is_mock: boolean;
}

export interface SellerOffer {
  listing_price: string | null;
  shipping_price: string | null;
  landed_price: string | null;
  currency: string | null;
  fulfilment_channel: string;
  is_buy_box_winner: boolean | null;
  is_featured_merchant: boolean | null;
  is_prime: boolean | null;
  seller_feedback_rating: string | null;
  seller_feedback_count: number | null;
  ships_from_country: string | null;
  condition: string | null;
}

export interface ChangeEvent {
  id: string;
  created_at: string;
  event_type: string;
  confidence: "high" | "medium" | "low" | null;
  product: ProductRef;
  seller: SellerRef | null;
  old_value: Record<string, string | number | null> | null;
  new_value: Record<string, string | number | null> | null;
  scan_result_id: string;
  previous_scan_result_id: string | null;
}

export interface SellerDetail extends SellerSummary {
  notes: string | null;
  products: { product: ProductRef; presence: Presence; last_seen_at: string; latest_scan_at: string | null; current_offer: SellerOffer | null }[];
  recent_changes: ChangeEvent[];
}

export interface SellerComparison {
  sellers: SellerSummary[];
  rows: { product: ProductRef; cells: { seller_id: string; offer: SellerOffer | null }[] }[];
}

export interface ScanSnapshot {
  id: string;
  status: string;
  data_source: string;
  retrieved_at: string;
  total_offer_count: number | null;
  observed_offer_count: number;
  unique_seller_count: number | null;
  is_offer_list_truncated: boolean | null;
  lowest_observed_price: string | null;
  highest_observed_price: string | null;
  buy_box_price: string | null;
  currency: string | null;
  limitations: string[];
  error_code: string | null;
}

export interface OfferRow extends SellerOffer {
  position: number;
  seller: SellerRef | null;
  seller_tags: string[];
}

export interface TrendPoint {
  retrieved_at: string;
  status: string;
  total_offer_count: number | null;
  observed_offer_count: number;
  unique_seller_count: number | null;
  lowest_observed_price: string | null;
  highest_observed_price: string | null;
  is_offer_list_truncated: boolean | null;
  data_source: string;
}

export const PRESENCE_LABELS: Record<Presence, string> = {
  observed: "Selling now",
  no_longer_observed: "No longer seen",
  not_observed_inconclusive: "Not seen (list incomplete)",
  unknown: "Unknown (no usable scan)",
};

export const LIMITATION_LABELS: Record<string, string> = {
  MOCK_DATA: "Generated MOCK data, not real marketplace data.",
  SELLER_NAME_NOT_PROVIDED: "The marketplace API does not provide seller names; sellers are shown by ID.",
  SELLER_ID_NOT_PROVIDED: "Some offers came without a seller ID, so the seller count is unknown.",
  OFFER_LIST_TRUNCATED: "The marketplace returned only part of the offer list.",
  TOTAL_OFFER_COUNT_NOT_PROVIDED: "The marketplace did not report a total offer count.",
  SOURCE_UNAVAILABLE: "The data source could not provide data for this product.",
  PRODUCT_NOT_FOUND: "The product was not found on the marketplace.",
};

// ---- Alerts (M10) ----

export type AlertRuleType =
  | "new_seller"
  | "seller_gone"
  | "buy_box_changed"
  | "offer_count_change"
  | "seller_count_above"
  | "price_below"
  | "scan_failed";
export type AlertSeverity = "info" | "warning" | "critical";
export type AlertChannel = "in_app" | "email";
export type AlertStatus = "open" | "acknowledged" | "resolved";

export interface AlertRuleScope {
  product_ids: string[];
  brands: string[];
}

export interface AlertRule {
  id: string;
  name: string;
  rule_type: AlertRuleType;
  severity: AlertSeverity;
  params: Record<string, unknown>;
  scope: AlertRuleScope;
  channels: AlertChannel[];
  recipient_user_ids: string[];
  is_enabled: boolean;
  created_by: string | null;
  created_at: string;
  updated_at: string;
  open_alerts: number;
}

export interface AlertRuleList {
  items: AlertRule[];
  limit: number;
}

export interface AlertDeliveryInfo {
  channel: AlertChannel;
  recipient_user_id: string | null;
  recipient_email: string | null;
  status: "pending" | "sending" | "sent" | "failed" | "skipped";
  attempt_count: number;
  last_error: string | null;
  next_attempt_at: string | null;
  sent_at: string | null;
}

export interface AlertItem {
  id: string;
  alert_rule_id: string | null;
  rule_name: string | null;
  rule_type: AlertRuleType | null;
  severity: AlertSeverity;
  status: AlertStatus;
  title: string;
  body: string | null;
  details: Record<string, unknown>;
  product: ProductRef | null;
  seller: SellerRef | null;
  scan_result_id: string | null;
  scan_history_id: string | null;
  created_at: string;
  acknowledged_by: string | null;
  acknowledged_at: string | null;
  resolved_by: string | null;
  resolved_at: string | null;
  resolved_automatically: boolean;
  delivered_channels: AlertChannel[];
  deliveries: AlertDeliveryInfo[];
}

export interface AlertSummary {
  open: number;
  acknowledged: number;
  open_by_severity: Record<AlertSeverity, number>;
  failed_deliveries: number;
}

// ---- Reports (M11) ----

export type ReportType = "product" | "marketplace" | "brand" | "seller" | "scan_summary" | "errors" | "alerts";
export type ReportFormat = "csv" | "xlsx";
export type ReportStatus = "queued" | "running" | "completed" | "failed" | "expired";

export interface ReportExport {
  id: string;
  report_type: ReportType;
  format: ReportFormat;
  filters: Record<string, unknown>;
  status: ReportStatus;
  requested_by: string | null;
  requested_by_email: string | null;
  row_count: number | null;
  size_bytes: number | null;
  contains_mock: boolean | null;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  expires_at: string | null;
  file_name: string | null;
}

export interface ReportPage extends Page<ReportExport> {
  retention_days: number;
}

// ---- Browser extension (M12) ----

export interface ExtensionPairing {
  pairing_code: string;
  expires_at: string;
  organization_name: string;
}

export interface ExtensionDevice {
  id: string;
  name: string | null;
  user_id: string;
  user_email: string | null;
  scopes: string[];
  created_at: string;
  last_used_at: string | null;
  expires_at: string;
  revoked_at: string | null;
  is_current_user: boolean;
}

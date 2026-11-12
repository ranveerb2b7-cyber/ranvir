import { API_URL } from "./config";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

export async function call<T>(
  path: string,
  init: { method?: string; token?: string; body?: unknown } = {},
): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (init.token) headers.Authorization = `Bearer ${init.token}`;
  if (init.body !== undefined) headers["Content-Type"] = "application/json";
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      method: init.method ?? "GET",
      headers,
      body: init.body === undefined ? undefined : JSON.stringify(init.body),
      credentials: "omit",
    });
  } catch {
    throw new ApiError(0, "network_error", "SellerScope can't be reached. Check your connection.");
  }
  if (response.status === 204) return undefined as T;
  const data = (await response.json().catch(() => ({}))) as Record<string, unknown>;
  if (!response.ok) {
    const detail = typeof data.detail === "string" ? data.detail : (data.title as string | undefined);
    throw new ApiError(response.status, String(data.code ?? "http_error"), detail ?? "Request failed.");
  }
  return data as T;
}

export interface PairCompleted {
  token: string;
  expires_at: string;
  organization: { id: string; name: string };
  user_email: string;
}

export interface Snapshot {
  status: string;
  data_source: string;
  is_mock: boolean;
  retrieved_at: string;
  total_offer_count: number | null;
  observed_offer_count: number | null;
  unique_seller_count: number | null;
  is_offer_list_truncated: boolean | null;
  lowest_observed_price: string | null;
  highest_observed_price: string | null;
  buy_box_price: string | null;
  currency: string | null;
  limitations: string[];
}

export interface LookupResult {
  identifier: string;
  tracked: boolean;
  product: { id: string; external_id: string; product_name: string | null; brand_name: string | null } | null;
  latest: Snapshot | null;
  last_attempt: { status: string; error_code: string | null; at: string } | null;
  active_scan: { job_id: string; status: string } | null;
  can_check: boolean;
  dashboard_url: string;
}

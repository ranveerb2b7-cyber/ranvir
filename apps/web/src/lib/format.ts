const dateTime = new Intl.DateTimeFormat("en-IN", { dateStyle: "medium", timeStyle: "short" });
const number = new Intl.NumberFormat("en-IN");

export const NOT_AVAILABLE = "Not available";

/** Money from the API's decimal string. Never invents a value: null in, null out. */
export function formatPrice(value: string | null | undefined, currency: string | null | undefined): string | null {
  if (value === null || value === undefined || !currency) return null;
  const amount = Number(value);
  if (!Number.isFinite(amount)) return null;
  return new Intl.NumberFormat("en-IN", { style: "currency", currency, maximumFractionDigits: 2 }).format(amount);
}

export function formatCount(value: number | null | undefined): string | null {
  return value === null || value === undefined ? null : number.format(value);
}

export function formatDateTime(value: string | null | undefined): string | null {
  return value ? dateTime.format(new Date(value)) : null;
}

/** Human text for API `reason` codes on unavailable metrics. */
export function reasonText(reason: string | null | undefined): string | undefined {
  if (!reason) return undefined;
  if (reason === "no_scans_yet") return "No scans have run yet.";
  if (reason === "change_tracking_not_available") return "Seller change tracking is not available yet.";
  return reason.charAt(0).toUpperCase() + reason.slice(1).replaceAll("_", " ") + ".";
}

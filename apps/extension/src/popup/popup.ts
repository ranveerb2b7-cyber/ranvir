import { ApiError, call, type LookupResult, type PairCompleted, type Snapshot } from "../lib/api";
import { WEB_URL } from "../lib/config";
import { detectProduct, type Detection } from "../lib/detect";
import { challengeFor, newVerifier } from "../lib/pkce";
import {
  clearConnection,
  clearPending,
  getConnection,
  getPending,
  saveConnection,
  savePending,
  type Connection,
} from "../lib/storage";

const app = document.getElementById("app") as HTMLElement;
const orgLabel = document.getElementById("org") as HTMLElement;
const NOT_AVAILABLE = "Not available";
const POLL_MS = 3000;

const LIMITATIONS: Record<string, string> = {
  MOCK_DATA: "MOCK data generated for testing, not real Amazon.in offers.",
  SELLER_NAME_NOT_PROVIDED: "Amazon doesn't provide seller names.",
  SELLER_ID_NOT_PROVIDED: "Some offers had no seller ID, so the seller count is unknown.",
  OFFER_LIST_TRUNCATED: "Amazon returned only part of the offer list.",
  TOTAL_OFFER_COUNT_NOT_PROVIDED: "Amazon didn't report a total offer count.",
  SOURCE_UNAVAILABLE: "The data source couldn't provide data.",
  PRODUCT_NOT_FOUND: "The product wasn't found on Amazon.in.",
};

// ------------------------------------------------------------------ tiny DOM helpers (no innerHTML)

type Child = Node | string | null | undefined | false;

function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  props: Partial<Record<string, string>> = {},
  ...children: Child[]
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value === undefined) continue;
    if (key === "class") node.className = value;
    else node.setAttribute(key, value);
  }
  for (const child of children) if (child) node.append(child);
  return node;
}

function render(...children: Child[]): void {
  app.replaceChildren(...children.filter((c): c is Node | string => Boolean(c)));
}

function button(label: string, onClick: () => void, cls = ""): HTMLButtonElement {
  const b = el("button", { type: "button", class: cls }, label);
  b.addEventListener("click", onClick);
  return b;
}

function value(text: string | null): Node {
  return text === null ? el("span", { class: "na" }, NOT_AVAILABLE) : document.createTextNode(text);
}

const dateTime = new Intl.DateTimeFormat("en-IN", { dateStyle: "medium", timeStyle: "short" });
const count = (n: number | null) => (n === null ? null : new Intl.NumberFormat("en-IN").format(n));
function price(amount: string | null, currency: string | null): string | null {
  if (amount === null || !currency) return null;
  return new Intl.NumberFormat("en-IN", { style: "currency", currency }).format(Number(amount));
}

// ------------------------------------------------------------------ pairing

async function startPairing(remember: boolean): Promise<void> {
  const verifier = newVerifier();
  await savePending({ verifier, remember, createdAt: Date.now() });
  const challenge = await challengeFor(verifier);
  const url = new URL("/extension/connect", WEB_URL);
  url.searchParams.set("challenge", challenge);
  url.searchParams.set("device", "Chrome extension");
  await chrome.tabs.create({ url: url.toString() });
  await showCodeEntry();
}

async function showConnect(message?: string): Promise<void> {
  orgLabel.textContent = "";
  const remember = el("input", { type: "checkbox", id: "remember" });
  render(
    el(
      "div",
      { class: "stack" },
      el("h1", {}, "Connect to SellerScope"),
      message ? el("p", { class: "error", role: "alert" }, message) : null,
      el("p", { class: "muted" }, "See your stored seller data for the Amazon.in product you're viewing. The extension only reads the page address."),
      el("label", { class: "row", for: "remember" }, remember, "Remember this browser"),
      button("Connect", () => void startPairing(remember.checked)),
      (await getPending()) ? button("I already have a code", () => void showCodeEntry(), "link") : null,
    ),
  );
}

async function showCodeEntry(error?: string): Promise<void> {
  const input = el("input", { type: "text", id: "code", autocomplete: "off", maxlength: "12", "aria-label": "Pairing code", placeholder: "XXXX-XXXX" });
  const form = el(
    "form",
    { class: "stack" },
    el("h1", {}, "Enter the code"),
    el("p", { class: "muted" }, "Approve the connection in the SellerScope tab, then enter the code it shows."),
    error ? el("p", { class: "error", role: "alert" }, error) : null,
    input,
    el("div", { class: "row" }, el("button", { type: "submit" }, "Connect"), button("Cancel", () => void cancelPairing(), "secondary")),
  );
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    void completePairing(input.value);
  });
  render(form);
  input.focus();
}

async function cancelPairing(): Promise<void> {
  await clearPending();
  await showConnect();
}

async function completePairing(code: string): Promise<void> {
  const pending = await getPending();
  if (!pending) return showConnect("The connection request expired. Start again.");
  try {
    const result = await call<PairCompleted>("/extension/pair/complete", {
      method: "POST",
      body: { pairing_code: code, code_verifier: pending.verifier },
    });
    await saveConnection(
      { token: result.token, organizationName: result.organization.name, userEmail: result.user_email, expiresAt: result.expires_at },
      pending.remember,
    );
    await clearPending();
    await main();
  } catch (err) {
    await showCodeEntry(err instanceof ApiError ? err.message : "Something went wrong.");
  }
}

// ------------------------------------------------------------------ product view

async function currentUrl(): Promise<string | undefined> {
  const forced = new URLSearchParams(location.search).get("tabId"); // used by automated tests
  if (forced) return (await chrome.tabs.get(Number(forced))).url;
  const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  return tab?.url; // readable only on sites the extension has access to (Amazon.in)
}

function snapshotView(s: Snapshot): Node {
  const usable = s.status === "ok" || s.status === "partial";
  const notes = s.limitations.map((code) => LIMITATIONS[code] ?? code);
  if (!usable) notes.unshift(`Amazon reported this product as ${s.status === "not_found" ? "not found" : "unavailable"}.`);
  if (usable && s.is_offer_list_truncated) notes.push("Observed figures are a lower bound.");
  return el(
    "div",
    { class: "stack" },
    el(
      "p",
      { class: "muted" },
      `Data as of ${dateTime.format(new Date(s.retrieved_at))}`,
      s.is_mock ? " " : null,
      s.is_mock ? el("span", { class: "badge" }, "MOCK") : null,
    ),
    el(
      "dl",
      {},
      el("dt", {}, "Total offers (Amazon)"), el("dd", {}, value(count(s.total_offer_count))),
      el("dt", {}, "Offers observed"), el("dd", {}, value(count(s.observed_offer_count))),
      el("dt", {}, "Unique sellers"), el("dd", {}, value(count(s.unique_seller_count))),
      el("dt", {}, "Lowest price"), el("dd", {}, value(price(s.lowest_observed_price, s.currency))),
      el("dt", {}, "Buy Box price"), el("dd", {}, value(price(s.buy_box_price, s.currency))),
    ),
    notes.length ? el("ul", { class: "notes" }, ...notes.map((n) => el("li", {}, n))) : null,
  );
}

let pollTimer: number | undefined;

async function showProduct(conn: Connection, detection: Extract<Detection, { kind: "product" }>, message?: string): Promise<void> {
  window.clearTimeout(pollTimer);
  render(el("p", { class: "muted" }, `Looking up ${detection.asin}…`));
  let result: LookupResult;
  try {
    result = await call<LookupResult>(`/extension/lookup?marketplace=${detection.marketplace}&id=${encodeURIComponent(detection.asin)}`, { token: conn.token });
  } catch (err) {
    return handleError(err);
  }
  const header = el(
    "div",
    {},
    el("h1", {}, result.product?.product_name ?? result.identifier),
    el("p", { class: "muted mono" }, `ASIN ${result.identifier}${result.product?.brand_name ? ` · ${result.product.brand_name}` : ""}`),
  );
  const open = el("a", { class: "button secondary", href: result.dashboard_url, target: "_blank", rel: "noopener" }, result.tracked ? "Open in SellerScope" : "Add in SellerScope");
  if (!result.tracked) {
    return render(el("div", { class: "stack" }, header, el("p", {}, "This product isn't in your SellerScope products."), open));
  }
  const checking = result.active_scan !== null;
  const check = result.can_check
    ? button(checking ? "Checking…" : "Check now", () => void checkNow(conn, detection))
    : null;
  if (check && checking) check.disabled = true;
  const failed =
    result.last_attempt?.status === "error" &&
    (!result.latest || new Date(result.last_attempt.at) > new Date(result.latest.retrieved_at));
  render(
    el(
      "div",
      { class: "stack" },
      header,
      message ? el("p", { role: "status" }, message) : null,
      result.latest
        ? el("div", { class: "card" }, snapshotView(result.latest))
        : el("p", { class: "muted" }, "Not scanned yet."),
      failed ? el("p", { class: "error" }, `The latest check failed (${result.last_attempt?.error_code ?? "error"}). Showing the last good data.`) : null,
      el("div", { class: "row" }, check, open),
    ),
  );
  if (checking) pollTimer = window.setTimeout(() => void showProduct(conn, detection), POLL_MS);
}

async function checkNow(conn: Connection, detection: Extract<Detection, { kind: "product" }>): Promise<void> {
  try {
    await call("/extension/check", { method: "POST", token: conn.token, body: { marketplace: detection.marketplace, id: detection.asin } });
    await showProduct(conn, detection, "Check started. This updates when it finishes.");
  } catch (err) {
    if (err instanceof ApiError && err.status !== 401) return showProduct(conn, detection, err.message);
    return handleError(err);
  }
}

async function handleError(err: unknown): Promise<void> {
  if (err instanceof ApiError && err.status === 401) {
    await clearConnection();
    return showConnect(`Disconnected: ${err.message}`);
  }
  render(el("p", { class: "error", role: "alert" }, err instanceof Error ? err.message : "Something went wrong."));
}

async function disconnect(conn: Connection): Promise<void> {
  try {
    await call("/extension/session", { method: "DELETE", token: conn.token });
  } catch {
    // Still forget the token locally; it can also be revoked in SellerScope settings.
  }
  await clearConnection();
  await showConnect();
}

async function main(): Promise<void> {
  const conn = await getConnection();
  if (!conn) return (await getPending()) ? showCodeEntry() : showConnect();
  orgLabel.replaceChildren(conn.organizationName, " · ", button("Disconnect", () => void disconnect(conn), "link"));
  const detection = detectProduct(await currentUrl());
  switch (detection.kind) {
    case "product":
      return showProduct(conn, detection);
    case "short_link":
      return render(el("p", {}, "Open the full Amazon.in product page to look it up."));
    case "other_amazon":
      return render(el("p", {}, "Only Amazon.in is supported."));
    case "amazon_in_other":
      return render(el("p", {}, "Open an Amazon.in product page to see its sellers."));
    default:
      return render(el("p", { class: "muted" }, "Open an Amazon.in product page to see your stored seller data."));
  }
}

void main();

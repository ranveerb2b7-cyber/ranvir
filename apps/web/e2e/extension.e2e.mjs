// End-to-end: the unpacked Chrome extension (M12) against the local stack.
// Amazon.in pages are served by Playwright routing (synthetic HTML, no request leaves the
// machine); the extension must use only the URL. Pairing (PKCE + one-time code), lookup,
// Check now (real worker), untracked/non-product pages, revocation and the permission review.
import assert from "node:assert/strict";
import { mkdtempSync, readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { join } from "node:path";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");

const BASE = process.env.E2E_BASE_URL ?? "http://localhost:3100";
const API = process.env.E2E_API_URL ?? "http://localhost:8000/api/v1";
const AUTH = process.env.E2E_AUTH_URL ?? "http://127.0.0.1:9999/auth/v1";
const EXT_DIR = process.env.E2E_EXTENSION_DIR;
const SHOTS = process.env.E2E_SCREENSHOTS;
const run = Date.now().toString(36);
const user = { email: `ext-${run}@example.com`, password: "ext-pass-1" };
const ASIN = "B0VICTIM01"; // multi-seller MOCK listing
const PRODUCT_URL = `https://www.amazon.in/Steel-Bottle-1L/dp/${ASIN}/ref=sr_1_1?th=1`;

assert.ok(EXT_DIR, "E2E_EXTENSION_DIR must point at the built extension");
const shot = async (page, name) => SHOTS && page.screenshot({ path: join(SHOTS, `${name}.png`), fullPage: true });
const steps = [];
const step = async (name, fn) => {
  await fn();
  steps.push(name);
  console.log(`  ✓ ${name}`);
};

const context = await chromium.launchPersistentContext(mkdtempSync(join(tmpdir(), "sellerscope-ext-")), {
  headless: true,
  channel: "chromium",
  viewport: { width: 1280, height: 860 },
  args: [`--disable-extensions-except=${EXT_DIR}`, `--load-extension=${EXT_DIR}`],
});
// Synthetic Amazon.in pages: nothing is fetched from Amazon.
const amazonHits = [];
await context.route(/^https:\/\/(www\.|m\.)?amazon\.in\//, (route) => {
  amazonHits.push(route.request().url());
  return route.fulfill({ contentType: "text/html", body: "<!doctype html><title>Amazon.in test page</title><h1>Product</h1>" });
});
const lookups = [];
context.on("request", (r) => {
  if (r.url().startsWith(`${API}/extension/lookup`)) lookups.push(new URL(r.url()));
});

let [worker] = context.serviceWorkers();
if (!worker) worker = await context.waitForEvent("serviceworker");
const extensionId = new URL(worker.url()).host;
const page = await context.newPage();
page.on("pageerror", (e) => console.error("page error:", e.message));

async function tabIdFor(urlPattern) {
  return worker.evaluate(async (pattern) => (await chrome.tabs.query({ url: pattern }))[0]?.id, urlPattern);
}

let amazonTab;
let popup;
async function openPopup() {
  const tabId = await tabIdFor("https://www.amazon.in/*");
  if (!popup || popup.isClosed()) popup = await context.newPage();
  await popup.goto(`chrome-extension://${extensionId}/popup.html?tabId=${tabId}`);
  return popup;
}

try {
  await step("permissions are minimal (manifest review)", async () => {
    const manifest = JSON.parse(readFileSync(join(EXT_DIR, "manifest.json"), "utf8"));
    assert.equal(manifest.manifest_version, 3);
    assert.deepEqual(manifest.permissions, ["storage"]);
    assert.equal(manifest.content_scripts, undefined, "no scripts injected into pages");
    assert.ok(!JSON.stringify(manifest).includes("<all_urls>"));
    assert.deepEqual(
      manifest.host_permissions.filter((h) => !h.startsWith(new URL(API).origin)),
      ["https://www.amazon.in/*", "https://amazon.in/*", "https://m.amazon.in/*"],
    );
  });

  await step("sign up and add a scanned product", async () => {
    await page.goto(`${BASE}/register`);
    await page.getByLabel("Work email").fill(user.email);
    await page.getByLabel("Password").fill(user.password);
    await page.getByRole("button", { name: "Create account" }).click();
    await page.waitForURL(/\/onboarding/);
    await page.getByLabel("Organization name").fill("Extension Co");
    await page.getByRole("button", { name: "Create organization" }).click();
    await page.waitForURL(/\/dashboard/);
    const orgId = await page.evaluate(() => window.localStorage.getItem("sellerscope.currentOrg"));
    const { access_token } = await (
      await fetch(`${AUTH}/token?grant_type=password`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(user) })
    ).json();
    const headers = { Authorization: `Bearer ${access_token}`, "X-Organization-Id": orgId, "Content-Type": "application/json" };
    const r = await fetch(`${API}/products`, { method: "POST", headers, body: JSON.stringify({ identifier: ASIN, product_name: "Steel bottle" }) });
    assert.equal(r.status, 201, await r.text());
  });

  await step("badge marks an Amazon.in product page (URL only)", async () => {
    amazonTab = await context.newPage();
    await amazonTab.goto(PRODUCT_URL);
    const tabId = await tabIdFor("https://www.amazon.in/*");
    await worker.evaluate(async (id) => {
      for (let i = 0; i < 50 && (await chrome.action.getBadgeText({ tabId: id })) !== "●"; i++) {
        await new Promise((r) => setTimeout(r, 100));
      }
    }, tabId);
    assert.equal(await worker.evaluate((id) => chrome.action.getBadgeText({ tabId: id }), tabId), "●");
    // The page is untouched: no extension script ran in it.
    assert.equal(await amazonTab.evaluate(() => document.documentElement.outerHTML.includes("SellerScope")), false);
  });

  await step("pair: approve on the web, enter the one-time code in the extension", async () => {
    const p = await openPopup();
    await p.getByRole("heading", { name: "Connect to SellerScope" }).waitFor();
    const [connectTab] = await Promise.all([context.waitForEvent("page"), p.getByRole("button", { name: "Connect" }).click()]);
    await connectTab.waitForURL(/\/extension\/connect\?challenge=[A-Za-z0-9_-]{43,}/);
    await connectTab.getByText("Connect Chrome extension to Extension Co").waitFor();
    await connectTab.getByRole("button", { name: "Approve and show code" }).click();
    const code = (await connectTab.getByTestId("pairing-code").textContent()).trim();
    assert.match(code, /^[A-Z2-9]{4}-[A-Z2-9]{4}$/);
    await shot(connectTab, "50-extension-connect");
    await connectTab.close();

    await p.getByLabel("Pairing code").fill("WRON-GCOD");
    await p.getByRole("button", { name: "Connect" }).click();
    await p.getByRole("alert").getByText(/invalid, expired or already used/).waitFor();
    await p.getByLabel("Pairing code").fill(code.toLowerCase());
    await p.getByRole("button", { name: "Connect" }).click();
    await p.getByText("Extension Co").waitFor();
  });

  await step("lookup shows stored data: not scanned yet, then Check now via the worker", async () => {
    const p = await openPopup();
    await p.getByRole("heading", { name: "Steel bottle" }).waitFor();
    await p.getByText("Not scanned yet.").waitFor();
    await p.getByRole("button", { name: "Check now" }).click();
    await p.getByText("Check started.").waitFor();
    await p.getByText(/^Data as of /).waitFor({ timeout: 60_000 }); // the popup polls until done
    await p.getByText("MOCK", { exact: true }).waitFor();
    await p.getByRole("button", { name: "Check now" }).waitFor();
    const sellers = await p.locator("dt", { hasText: "Unique sellers" }).locator("+ dd").textContent();
    assert.match(sellers, /^\d+$/);
    const link = await p.getByRole("link", { name: "Open in SellerScope" }).getAttribute("href");
    assert.match(link, new RegExp(`^${BASE}/products/[0-9a-f-]{36}$`));
    await shot(p, "51-extension-popup");
    // Only the ASIN is sent, never the page address or content.
    assert.ok(lookups.length > 0 && lookups.every((u) => u.searchParams.get("id") === ASIN), lookups.join("\n"));
  });

  await step("untracked and non-product pages", async () => {
    await amazonTab.goto("https://www.amazon.in/dp/B0NOTTRACK");
    let p = await openPopup();
    await p.getByText("This product isn't in your SellerScope products.").waitFor();
    assert.match(await p.getByRole("link", { name: "Add in SellerScope" }).getAttribute("href"), /\/products\?q=B0NOTTRACK$/);
    await amazonTab.goto("https://www.amazon.in/s?k=steel+bottle");
    p = await openPopup();
    await p.getByText("Open an Amazon.in product page to see its sellers.").waitFor();
    assert.ok(amazonHits.every((u) => u.startsWith("https://www.amazon.in/")), "only routed test pages");
  });

  await step("revoked in Settings: the extension is disconnected", async () => {
    await page.goto(`${BASE}/settings`);
    const devices = page.getByRole("list", { name: "Connected browsers" });
    await devices.getByText("Chrome extension").waitFor();
    await devices.getByRole("button", { name: "Disconnect" }).click();
    await page.getByText("No connected browsers.").waitFor();
    await amazonTab.goto(PRODUCT_URL);
    const p = await openPopup();
    await p.getByRole("alert").getByText(/Disconnected: This connection was revoked or has expired\./).waitFor();
    await p.getByRole("heading", { name: "Connect to SellerScope" }).waitFor();
  });

  console.log(`\n${steps.length} extension e2e steps passed`);
} catch (err) {
  if (popup && !popup.isClosed()) await shot(popup, "zz-extension-popup-failure");
  await shot(page, "zz-extension-failure");
  console.error(`\nFAILED after ${steps.length} steps:`, err);
  process.exitCode = 1;
} finally {
  await context.close();
}

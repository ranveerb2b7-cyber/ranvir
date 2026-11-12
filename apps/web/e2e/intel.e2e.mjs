// End-to-end: change history, product detail with charts, seller intelligence, comparison (M8).
// MOCK listings drift every MOCK_EPOCH_SECONDS (5s in run-local.sh), so a rescan shows changes.
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { join } from "node:path";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");

const BASE = process.env.E2E_BASE_URL ?? "http://localhost:3100";
const API = process.env.E2E_API_URL ?? "http://localhost:8000/api/v1";
const AUTH = process.env.E2E_AUTH_URL ?? "http://127.0.0.1:9999/auth/v1";
const SHOTS = process.env.E2E_SCREENSHOTS;
const run = Date.now().toString(36);
const user = { email: `intel-${run}@example.com`, password: "intel-pass-1" };
// B0VICTIM01..03 are multi-seller MOCK listings (they drift between epochs).
const ASINS = ["B0VICTIM01", "B0VICTIM02", "B0VICTIM03"];

const shot = async (page, name) => SHOTS && page.screenshot({ path: join(SHOTS, `${name}.png`), fullPage: true });
const steps = [];
const step = async (name, fn) => {
  await fn();
  steps.push(name);
  console.log(`  ✓ ${name}`);
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
page.on("pageerror", (e) => console.error("page error:", e.message));

async function scanAll() {
  await page.goto(`${BASE}/products`);
  await page.getByRole("button", { name: "Scan all monitored" }).click();
  await page.waitForURL(/\/history\/[0-9a-f-]{36}$/);
  await page.getByText(`${ASINS.length} of ${ASINS.length}`).waitFor({ timeout: 60_000 });
}

try {
  await step("sign up, add multi-seller products", async () => {
    await page.goto(`${BASE}/register`);
    await page.getByLabel("Work email").fill(user.email);
    await page.getByLabel("Password").fill(user.password);
    await page.getByRole("button", { name: "Create account" }).click();
    await page.waitForURL(/\/onboarding/);
    await page.getByLabel("Organization name").fill("Intel Co");
    await page.getByRole("button", { name: "Create organization" }).click();
    await page.waitForURL(/\/dashboard/);
    const orgId = await page.evaluate(() => window.localStorage.getItem("sellerscope.currentOrg"));
    const { access_token } = await (
      await fetch(`${AUTH}/token?grant_type=password`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(user) })
    ).json();
    for (const asin of ASINS) {
      const r = await fetch(`${API}/products`, {
        method: "POST",
        headers: { Authorization: `Bearer ${access_token}`, "X-Organization-Id": orgId, "Content-Type": "application/json" },
        body: JSON.stringify({ identifier: asin, product_name: `Product ${asin.slice(-2)}`, brand_name: "Intel" }),
      });
      assert.equal(r.status, 201, await r.text());
    }
  });

  await step("first scan is a baseline: no changes yet", async () => {
    await scanAll();
    await page.goto(`${BASE}/history`);
    await page.getByRole("tab", { name: "Changes" }).click();
    await page.getByText("No changes detected yet.").waitFor();
  });

  await step("rescan after the listings drift: changes are detected", async () => {
    await sleep(6_000); // let the MOCK epoch roll over
    await scanAll();
    await page.goto(`${BASE}/history`);
    await page.getByRole("tab", { name: "Changes" }).click();
    await page.getByText(/New seller: MOCK\d{4} started offering this product\./).first().waitFor();
    await page.getByText(/is no longer offering this product\./).first().waitFor();
    await shot(page, "21-changes-feed");
  });

  let sellerUrl;
  await step("product detail: snapshot, offers, charts, change history", async () => {
    await page.goto(`${BASE}/products`);
    await page.getByRole("link", { name: "B0VICTIM01" }).first().click();
    await page.waitForURL(/\/products\/[0-9a-f-]{36}$/);
    await page.getByRole("heading", { name: "Latest scan", exact: true }).waitFor();
    await page.getByText("Generated MOCK data, not real marketplace data.").waitFor();
    await page.getByRole("heading", { name: "Offers in the latest scan" }).waitFor();
    await page.locator("figure svg.recharts-surface").nth(1).waitFor(); // both trend charts render
    assert.ok((await page.locator("figure .recharts-line").count()) >= 4, "lines drawn");
    await page.getByText(/New seller: MOCK\d{4}/).first().waitFor();
    await page.getByRole("button", { name: "Show as table" }).first().click();
    await page.getByRole("columnheader", { name: "Unique sellers" }).waitFor();
    await shot(page, "22-product-detail");
    const sellerLink = page.locator("table tbody tr td a[href^='/sellers/']").first();
    sellerUrl = await sellerLink.getAttribute("href");
    await sellerLink.click();
    await page.waitForURL(/\/sellers\/[0-9a-f-]{36}$/);
  });

  await step("label a seller with your own name and tags", async () => {
    await page.getByLabel("Name").fill("Blue Traders");
    await page.getByLabel("Tags").fill("unauthorized, watch");
    await page.getByRole("button", { name: "Save labels" }).click();
    await page.getByText("Saved.").waitFor();
    await page.getByRole("heading", { name: "Blue Traders" }).waitFor();
    await page.getByText("Selling now").first().waitFor();
    await shot(page, "23-seller-detail");
  });

  await step("seller list: tag filter and search", async () => {
    await page.getByRole("link", { name: "Seller Intelligence" }).first().click();
    await page.waitForURL(/\/sellers$/);
    await page.getByRole("link", { name: "Blue Traders" }).waitFor(); // page loaded and interactive
    await page.getByLabel("Tag").fill("unauthorized");
    await page.waitForFunction(() => document.querySelectorAll("table tbody tr").length === 1);
    await page.getByRole("link", { name: "Blue Traders" }).waitFor();
    await page.getByLabel("Tag").fill("");
    await page.getByLabel("Search sellers").fill("blue");
    await page.getByRole("link", { name: "Blue Traders" }).waitFor();
    await page.getByLabel("Search sellers").fill("");
  });

  await step("compare two sellers", async () => {
    await page.locator("table tbody tr").nth(1).waitFor();
    const boxes = page.locator("table tbody input[type=checkbox]");
    await boxes.nth(0).check();
    await boxes.nth(1).check();
    await page.getByRole("button", { name: "Compare (2)" }).click();
    await page.waitForURL(/\/sellers\/compare\?ids=/);
    await page.getByRole("heading", { name: "Compare sellers" }).waitFor();
    await page.locator("table tbody tr").first().waitFor();
    await shot(page, "24-compare");
    assert.ok(sellerUrl);
  });

  await step("dashboard counts new sellers from detected changes", async () => {
    await page.getByRole("link", { name: "Dashboard" }).click();
    const tile = page.locator("div.rounded-lg", { hasText: "New sellers detected" });
    const value = await tile.locator("div.text-3xl").textContent({ timeout: 30_000 });
    assert.ok(Number(value) >= 1, `new sellers: ${value}`);
  });

  console.log(`\n${steps.length} intel e2e steps passed`);
} catch (err) {
  await shot(page, "zz-intel-failure");
  console.error(`\nFAILED after ${steps.length} steps:`, err);
  process.exitCode = 1;
} finally {
  await browser.close();
}

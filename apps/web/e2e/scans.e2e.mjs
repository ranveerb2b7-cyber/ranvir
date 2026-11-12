// End-to-end: scanning (M6) with the MOCK connector, processed by the real Celery worker.
// Env: E2E_BASE_URL, E2E_API_URL, E2E_AUTH_URL, E2E_SCREENSHOTS
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
const user = { email: `scanner-${run}@example.com`, password: "scans-pass-1" };
const ASINS = ["B0SCANE2E1", "B0SCANE2E2", "B0SCANE2E3", "B0SCANE2E4"];

const shot = async (page, name) => SHOTS && page.screenshot({ path: join(SHOTS, `${name}.png`), fullPage: true });
const steps = [];
const step = async (name, fn) => {
  await fn();
  steps.push(name);
  console.log(`  ✓ ${name}`);
};

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
page.on("pageerror", (e) => console.error("page error:", e.message));

try {
  await step("sign up; MOCK DATA banner is shown", async () => {
    await page.goto(`${BASE}/register`);
    await page.getByLabel("Work email").fill(user.email);
    await page.getByLabel("Password").fill(user.password);
    await page.getByRole("button", { name: "Create account" }).click();
    await page.waitForURL(/\/onboarding/);
    await page.getByLabel("Organization name").fill("Scan Co");
    await page.getByRole("button", { name: "Create organization" }).click();
    await page.waitForURL(/\/dashboard/);
    await page.getByText("MOCK DATA: scans in this environment produce generated test data").waitFor();
  });

  await step("add products", async () => {
    const orgId = await page.evaluate(() => window.localStorage.getItem("sellerscope.currentOrg"));
    const { access_token } = await (
      await fetch(`${AUTH}/token?grant_type=password`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(user),
      })
    ).json();
    for (const asin of ASINS) {
      const r = await fetch(`${API}/products`, {
        method: "POST",
        headers: { Authorization: `Bearer ${access_token}`, "X-Organization-Id": orgId, "Content-Type": "application/json" },
        body: JSON.stringify({ identifier: asin, brand_name: "Scanned" }),
      });
      assert.equal(r.status, 201, await r.text());
    }
  });

  await step("scan selected products; the worker completes the job", async () => {
    await page.getByRole("link", { name: "Product Mapping" }).click();
    await page.getByText("1–4 of 4").waitFor();
    await page.getByLabel("Select all on this page").check();
    await page.getByRole("button", { name: "Scan now" }).click();
    await page.waitForURL(/\/history\/[0-9a-f-]{36}$/);
    await page.getByText("4 of 4").waitFor({ timeout: 60_000 });
    const status = await page.locator("span.rounded-full").first().textContent();
    assert.ok(["Completed", "Completed with issues"].includes(status), status);
    assert.ok((await page.getByText("MOCK", { exact: true }).count()) >= 1);
    await shot(page, "17-scan-job");
  });

  await step("products show scanned values with MOCK labels", async () => {
    await page.getByRole("link", { name: "Product Mapping" }).click();
    await page.getByText("1–4 of 4").waitFor();
    const statuses = await page.locator("table tbody tr td:nth-child(11)").allTextContents(); // checkbox + 10 columns: status
    assert.ok(statuses.every((s) => !s.includes("Not scanned yet")), statuses.join(" | "));
    assert.ok(statuses.filter((s) => s.includes("MOCK")).length >= 1);
    await shot(page, "18-products-scanned");
  });

  await step("dashboard now reports scan metrics", async () => {
    await page.getByRole("link", { name: "Dashboard" }).click();
    const tile = page.locator("div.rounded-lg", { hasText: "Products successfully scanned" });
    await tile.locator("div.text-3xl").waitFor();
    // Seller change tracking arrives in M8: until then this must not read as "0".
    const newSellers = page.locator("div.rounded-lg", { hasText: "New sellers detected" });
    await newSellers.getByText("Not available", { exact: true }).waitFor();
    await newSellers.getByText("Seller change tracking is not available yet.").waitFor();
    await shot(page, "19-dashboard-scanned");
  });

  await step("scan all monitored creates a second job; history lists both", async () => {
    await page.getByRole("link", { name: "Product Mapping" }).click();
    await page.getByRole("button", { name: "Scan all monitored" }).click();
    await page.waitForURL(/\/history\/[0-9a-f-]{36}$/);
    await page.getByText("4 of 4").waitFor({ timeout: 60_000 });
    await page.getByRole("link", { name: "Scan History" }).first().click();
    await page.waitForURL(/\/history$/);
    await page.getByText(/Product scans this month: 8 of/).waitFor();
    await page.locator("table tbody tr").nth(1).waitFor();
    assert.equal(await page.locator("table tbody tr").count(), 2);
    await shot(page, "20-scan-history");
  });

  console.log(`\n${steps.length} scan e2e steps passed`);
} catch (err) {
  await shot(page, "zz-scans-failure");
  console.error(`\nFAILED after ${steps.length} steps:`, err);
  process.exitCode = 1;
} finally {
  await browser.close();
}

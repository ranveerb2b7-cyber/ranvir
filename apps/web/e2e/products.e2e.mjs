// End-to-end: product management and dashboard (M4). Runs against the stack from run-local.sh.
// Env: E2E_BASE_URL, E2E_API_URL, E2E_AUTH_URL (stub auth), E2E_SCREENSHOTS
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
const user = { email: `catalog-${run}@example.com`, password: "products-pass-1" };

const shot = async (page, name) => SHOTS && page.screenshot({ path: join(SHOTS, `${name}.png`), fullPage: true });
const steps = [];
const step = async (name, fn) => {
  await fn();
  steps.push(name);
  console.log(`  ✓ ${name}`);
};
const rows = (page) => page.locator("table tbody tr");

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
page.on("pageerror", (e) => console.error("page error:", e.message));
let orgId;

try {
  await step("sign up and create organization", async () => {
    await page.goto(`${BASE}/register`);
    await page.getByLabel("Work email").fill(user.email);
    await page.getByLabel("Password").fill(user.password);
    await page.getByRole("button", { name: "Create account" }).click();
    await page.waitForURL(/\/onboarding/);
    await page.getByLabel("Organization name").fill("Catalog Co");
    await page.getByRole("button", { name: "Create organization" }).click();
    await page.waitForURL(/\/dashboard/);
    orgId = await page.evaluate(() => window.localStorage.getItem("sellerscope.currentOrg"));
    assert.ok(orgId);
  });

  await step("empty dashboard: real zero for products, Not available for scan metrics", async () => {
    const tile = (label) => page.locator("div.rounded-lg", { hasText: label });
    await tile("Total products monitored").getByText("0", { exact: true }).waitFor();
    await tile("Products successfully scanned").getByText("Not available").waitFor();
    await tile("Total offers observed").getByText("No scans have run yet.").waitFor();
  });

  await step("add a product from an Amazon.in link", async () => {
    await page.getByRole("link", { name: "Product Mapping" }).click();
    await page.getByText("No products yet.").waitFor();
    await page.getByRole("button", { name: "Add product" }).click();
    await page.getByLabel("ASIN or Amazon.in product link").fill("https://www.amazon.in/Steel-Bottle/dp/B0E2E00001/ref=sr_1_1");
    await page.getByText("ASIN B0E2E00001 looks valid").waitFor();
    await page.getByLabel("Product name (optional)").fill("Steel Bottle 1L");
    await page.getByLabel("Brand (optional)").fill("Hydra");
    await page.getByRole("dialog").getByRole("button", { name: "Add product" }).click();
    await rows(page).first().getByRole("cell", { name: "B0E2E00001", exact: true }).waitFor();
    const row = rows(page).first();
    assert.equal(await row.getByText("Not available").count(), 5); // offers, sellers, 2 prices, last scanned
    await row.getByText("Not scanned yet").waitFor();
  });

  await step("duplicate and invalid identifiers are caught before saving", async () => {
    await page.getByRole("button", { name: "Add product" }).click();
    const input = page.getByLabel("ASIN or Amazon.in product link");
    await input.fill("b0e2e00001");
    await page.getByText("B0E2E00001 is already in your products.").waitFor();
    assert.ok(await page.getByRole("dialog").getByRole("button", { name: "Add product" }).isDisabled());
    await input.fill("https://amzn.in/d/abc");
    await page.getByText("Short links (amzn.in, amzn.to)").waitFor();
    await shot(page, "10-add-product-invalid");
    await page.getByRole("button", { name: "Cancel" }).click();
  });

  await step("bulk-create 30 more products through the API", async () => {
    const res = await fetch(`${AUTH}/token?grant_type=password`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(user),
    });
    const { access_token } = await res.json();
    for (let i = 2; i <= 31; i++) {
      const r = await fetch(`${API}/products`, {
        method: "POST",
        headers: { Authorization: `Bearer ${access_token}`, "X-Organization-Id": orgId, "Content-Type": "application/json" },
        body: JSON.stringify({
          identifier: `B0E2E${String(i).padStart(5, "0")}`,
          product_name: `Item ${i}`,
          brand_name: i % 2 ? "Hydra" : "Zen",
        }),
      });
      assert.equal(r.status, 201, await r.text());
    }
    await page.reload();
    await page.getByText("1–25 of 31").waitFor();
  });

  await step("paginate", async () => {
    assert.equal(await rows(page).count(), 25);
    await page.getByRole("button", { name: "Next" }).click();
    await page.getByText("26–31 of 31").waitFor();
    assert.equal(await rows(page).count(), 6);
    assert.match(page.url(), /page=2/);
  });

  await step("search and filter by brand (URL keeps the filters)", async () => {
    await page.getByLabel("Search products").fill("B0E2E0001");
    await page.getByText("1–10 of 10").waitFor(); // B0E2E00010..00019
    await page.getByLabel("Brand").selectOption("Zen");
    await page.getByText("1–5 of 5").waitFor();
    assert.match(page.url(), /q=B0E2E0001/);
    assert.match(page.url(), /brand=Zen/);
    await page.reload();
    await page.getByText("1–5 of 5").waitFor();
    await page.getByLabel("Search products").fill("");
    await page.getByLabel("Brand").selectOption("");
    await page.getByText("1–25 of 31").waitFor();
  });

  await step("sort by ASIN", async () => {
    await page.getByRole("button", { name: "ASIN" }).click();
    await rows(page).first().getByRole("cell", { name: "B0E2E00001", exact: true }).waitFor();
    await page.getByRole("button", { name: "ASIN" }).click();
    await rows(page).first().getByRole("cell", { name: "B0E2E00031", exact: true }).waitFor();
    await shot(page, "11-products");
  });

  await step("bulk set brand on selected rows", async () => {
    page.once("dialog", (d) => d.accept("Acme"));
    await page.getByLabel("Select B0E2E00031").check();
    await page.getByLabel("Select B0E2E00030").check();
    await page.getByText("2 selected").waitFor();
    await page.getByRole("button", { name: "Set brand" }).click();
    await page.getByText("Updated 2 product(s).").waitFor();
    await page.getByLabel("Brand").selectOption("Acme");
    await page.getByText("1–2 of 2").waitFor();
    await page.getByLabel("Brand").selectOption("");
  });

  await step("edit a product and stop monitoring it", async () => {
    await page.getByRole("button", { name: "Edit B0E2E00031" }).click();
    await page.getByLabel("Product name").fill("Renamed item");
    await page.getByLabel("Monitor this product").uncheck();
    await page.getByRole("button", { name: "Save" }).click();
    await rows(page).first().getByText("Renamed item").waitFor();
  });

  await step("dashboard reflects products, still no fabricated scan data", async () => {
    await page.getByRole("link", { name: "Dashboard" }).click();
    const monitored = page.locator("div.rounded-lg", { hasText: "Total products monitored" });
    await monitored.getByText("30", { exact: true }).waitFor(); // 31 products, 1 not monitored
    for (const label of ["Products successfully scanned", "Total offers observed", "Products with unavailable data"]) {
      await page.locator("div.rounded-lg", { hasText: label }).getByText("Not available").waitFor();
    }
    await shot(page, "12-dashboard");
  });

  await step("mobile product cards without horizontal scroll", async () => {
    const mobile = await browser.newPage({ viewport: { width: 375, height: 800 } });
    await mobile.context().addCookies(await page.context().cookies());
    await mobile.goto(`${BASE}/products`);
    await mobile.locator("li", { hasText: "B0E2E" }).first().waitFor(); // card layout, not the hidden table
    const width = await mobile.evaluate(() => document.documentElement.scrollWidth);
    assert.ok(width <= 375, `scrollWidth ${width}`);
    if (SHOTS) await mobile.screenshot({ path: join(SHOTS, "13-products-mobile.png") });
    await mobile.close();
  });

  console.log(`\n${steps.length} product e2e steps passed`);
} catch (err) {
  await shot(page, "zz-products-failure");
  console.error(`\nFAILED after ${steps.length} steps:`, err);
  process.exitCode = 1;
} finally {
  await browser.close();
}

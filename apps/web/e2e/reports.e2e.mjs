// End-to-end: report exports prepared by the Celery worker (reports queue), downloaded as files
// through the browser, with MOCK labelling and blanks-not-zeros checked in the file (M11).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { join } from "node:path";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");

const BASE = process.env.E2E_BASE_URL ?? "http://localhost:3100";
const API = process.env.E2E_API_URL ?? "http://localhost:8000/api/v1";
const AUTH = process.env.E2E_AUTH_URL ?? "http://127.0.0.1:9999/auth/v1";
const SHOTS = process.env.E2E_SCREENSHOTS;
const run = Date.now().toString(36);
const user = { email: `reports-${run}@example.com`, password: "reports-pass-1" };
// B0VICTIM01 has MOCK offers; B0NEVERSCN is never scanned (its figures must be blank).
const SCANNED = "B0VICTIM01";
const UNSCANNED = "B0NEVERSCN";

const shot = async (page, name) => SHOTS && page.screenshot({ path: join(SHOTS, `${name}.png`), fullPage: true });
const steps = [];
const step = async (name, fn) => {
  await fn();
  steps.push(name);
  console.log(`  ✓ ${name}`);
};

const browser = await chromium.launch();
const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, acceptDownloads: true });
const page = await context.newPage();
page.on("pageerror", (e) => console.error("page error:", e.message));

/** Minimal RFC 4180 parser (quoted fields, doubled quotes). */
function parseCsv(text) {
  const rows = [];
  let row = [];
  let field = "";
  let quoted = false;
  const endField = () => {
    row.push(field);
    field = "";
  };
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (quoted) {
      if (c === '"' && text[i + 1] === '"') {
        field += '"';
        i++;
      } else if (c === '"') quoted = false;
      else field += c;
    } else if (c === '"') quoted = true;
    else if (c === ",") endField();
    else if (c === "\n" || c === "\r") {
      if (c === "\r" && text[i + 1] === "\n") i++;
      endField();
      rows.push(row);
      row = [];
    } else field += c;
  }
  if (field || row.length) {
    endField();
    rows.push(row);
  }
  const [header, ...body] = rows;
  return body.map((r) => Object.fromEntries(header.map((h, i) => [h, r[i]])));
}

async function createReport(label, format) {
  await page.getByLabel("Report", { exact: true }).selectOption({ label });
  await page.getByLabel(format === "csv" ? "CSV" : "Excel (.xlsx)", { exact: true }).check();
  const table = page.getByRole("table", { name: "Reports" });
  const before = (await table.count()) ? await table.getByRole("row").count() : 1;
  await page.getByRole("button", { name: "Create report" }).click();
  // The new export is the newest (first) row once the list has grown.
  await page.waitForFunction(
    (n) => document.querySelectorAll('table[aria-label="Reports"] tr').length === n + 1,
    before,
  );
  const row = table.getByRole("row").nth(1);
  await row.getByText(format, { exact: true }).waitFor();
  await row.getByText(label).waitFor();
  await row.getByText("Ready").waitFor({ timeout: 60_000 }); // prepared by the worker
  return row;
}

async function downloadFrom(row) {
  const [download] = await Promise.all([page.waitForEvent("download"), row.getByRole("button", { name: /^Download/ }).click()]);
  return { name: download.suggestedFilename(), data: readFileSync(await download.path()) };
}

try {
  await step("sign up, add products, scan one", async () => {
    await page.goto(`${BASE}/register`);
    await page.getByLabel("Work email").fill(user.email);
    await page.getByLabel("Password").fill(user.password);
    await page.getByRole("button", { name: "Create account" }).click();
    await page.waitForURL(/\/onboarding/);
    await page.getByLabel("Organization name").fill("Reports Co");
    await page.getByRole("button", { name: "Create organization" }).click();
    await page.waitForURL(/\/dashboard/);
    const orgId = await page.evaluate(() => window.localStorage.getItem("sellerscope.currentOrg"));
    const { access_token } = await (
      await fetch(`${AUTH}/token?grant_type=password`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(user) })
    ).json();
    const headers = { Authorization: `Bearer ${access_token}`, "X-Organization-Id": orgId, "Content-Type": "application/json" };
    for (const [asin, name] of [[SCANNED, "Scanned bottle"], [UNSCANNED, "=SUM(1,2)"]]) {
      const r = await fetch(`${API}/products`, { method: "POST", headers, body: JSON.stringify({ identifier: asin, product_name: name, brand_name: "Rep" }) });
      assert.equal(r.status, 201, await r.text());
    }
    await page.goto(`${BASE}/products`);
    await page.getByLabel(`Select ${SCANNED}`).check();
    await page.getByRole("button", { name: "Scan now" }).click();
    await page.waitForURL(/\/history\/[0-9a-f-]{36}$/);
    await page.getByText("1 of 1").waitFor({ timeout: 60_000 });
  });

  await step("products report as CSV: blanks with reasons, MOCK labelled, formulas neutralised", async () => {
    await page.getByRole("link", { name: "Reports" }).click();
    await page.getByText("No reports yet.").waitFor();
    const row = await createReport("Products", "csv");
    await row.getByText("MOCK").waitFor();
    const { name, data } = await downloadFrom(row);
    assert.match(name, /^sellerscope-product-\d{8}-\d{4}\.csv$/);
    const rows = parseCsv(data.toString("utf8").replace(/^\uFEFF/, ""));
    const scanned = rows.find((r) => r.ASIN === SCANNED);
    const unscanned = rows.find((r) => r.ASIN === UNSCANNED);
    assert.equal(scanned["Data source"], "MOCK");
    assert.match(scanned.Notes, /MOCK data/);
    assert.match(scanned["Offers observed"], /^\d+$/);
    // Formula text is neutralised; unknown figures are empty (not 0) and explained.
    assert.equal(unscanned["Product name"], "'=SUM(1,2)");
    for (const col of ["Total offers (reported by Amazon)", "Offers observed", "Unique sellers", "Lowest price"]) {
      assert.equal(unscanned[col], "", col);
    }
    assert.equal(unscanned.Notes, "Not scanned yet.");
    await shot(page, "40-reports");
  });

  await step("products report as Excel", async () => {
    const row = await createReport("Products", "xlsx");
    const { name, data } = await downloadFrom(row);
    assert.match(name, /\.xlsx$/);
    assert.equal(data.subarray(0, 2).toString(), "PK", "an Excel (zip) file");
  });

  await step("scan summary and validation of the date range", async () => {
    await page.getByLabel("Report", { exact: true }).selectOption({ label: "Scan summary" });
    await page.getByLabel("From").fill("2026-12-31");
    await page.getByLabel("To").fill("2026-01-01");
    await page.getByRole("button", { name: "Create report" }).click();
    await page.getByRole("alert").getByText(/must be on or before/).waitFor();
    await page.getByLabel("From").fill("");
    await page.getByLabel("To").fill("");
    const row = await createReport("Scan summary", "csv");
    await row.getByText("Last 30 days").waitFor();
    const { data } = await downloadFrom(row);
    const jobs = parseCsv(data.toString("utf8").replace(/^\uFEFF/, ""));
    assert.equal(jobs.length, 1, "the one scan job");
    assert.equal(jobs[0]["Requested by"], user.email);
    assert.equal(jobs[0].Completed, "1");
  });

  await step("delete a report", async () => {
    const table = page.getByRole("table", { name: "Reports" });
    const before = await table.getByRole("row").count();
    await table.getByRole("row").nth(1).getByRole("button", { name: "Delete" }).click();
    await page.waitForFunction((n) => document.querySelectorAll('table[aria-label="Reports"] tr').length === n - 1, before);
  });

  await step("mobile layout", async () => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.reload();
    await page.getByRole("table", { name: "Reports" }).waitFor();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
    assert.equal(overflow, false, "no page-level horizontal scroll on phones");
    // Actions are reachable without scrolling the table sideways.
    const button = page.getByRole("button", { name: /^Download/ }).first();
    const box = await button.boundingBox();
    assert.ok(box && box.x + box.width <= 390, `download button visible: ${JSON.stringify(box)}`);
    await shot(page, "41-reports-mobile");
  });

  console.log(`\n${steps.length} reports e2e steps passed`);
} catch (err) {
  await shot(page, "zz-reports-failure");
  console.error(`\nFAILED after ${steps.length} steps:`, err);
  process.exitCode = 1;
} finally {
  await browser.close();
}

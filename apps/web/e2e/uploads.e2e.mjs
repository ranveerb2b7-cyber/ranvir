// End-to-end: product file upload (M5). Needs the full stack from run-local.sh, including the
// Celery worker that parses uploads. Env: E2E_BASE_URL, E2E_SCREENSHOTS, E2E_WORKDIR
import assert from "node:assert/strict";
import { readFileSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { join } from "node:path";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");

const BASE = process.env.E2E_BASE_URL ?? "http://localhost:3100";
const SHOTS = process.env.E2E_SCREENSHOTS;
const WORK = process.env.E2E_WORKDIR ?? "/tmp";
const run = Date.now().toString(36);
const user = { email: `uploader-${run}@example.com`, password: "uploads-pass-1" };

const shot = async (page, name) => SHOTS && page.screenshot({ path: join(SHOTS, `${name}.png`), fullPage: true });
const steps = [];
const step = async (name, fn) => {
  await fn();
  steps.push(name);
  console.log(`  ✓ ${name}`);
};

// A realistic messy file: valid rows, a URL, duplicates, bad values, Flipkart, a formula.
const csv = [
  "ASIN,Product name,Brand,Marketplace",
  "B0UPE2E001,Steel Bottle,Hydra,Amazon.in",
  "https://www.amazon.in/Yoga-Mat/dp/B0UPE2E002/ref=sr_1_2,Yoga Mat,Zen,",
  "B0UPE2E001,Steel Bottle (again),Hydra,",
  "nope,Broken row,,",
  ",Missing ASIN,Hydra,",
  'B0UPE2E003,"=HYPERLINK(""http://evil"",""x"")",,Flipkart',
  "B0UPE2E004,Lunch Box,Zen,",
].join("\r\n");
const csvPath = join(WORK, `catalog-${run}.csv`);
writeFileSync(csvPath, csv);
const badPath = join(WORK, `no-asin-${run}.csv`);
writeFileSync(badPath, "Name,Brand\r\nBottle,Hydra\r\n");
const txtPath = join(WORK, `notes-${run}.txt`);
writeFileSync(txtPath, "B0UPE2E001");

const browser = await chromium.launch();
const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, acceptDownloads: true });
const page = await context.newPage();
page.on("pageerror", (e) => console.error("page error:", e.message));

try {
  await step("sign up and create organization", async () => {
    await page.goto(`${BASE}/register`);
    await page.getByLabel("Work email").fill(user.email);
    await page.getByLabel("Password").fill(user.password);
    await page.getByRole("button", { name: "Create account" }).click();
    await page.waitForURL(/\/onboarding/);
    await page.getByLabel("Organization name").fill("Upload Co");
    await page.getByRole("button", { name: "Create organization" }).click();
    await page.waitForURL(/\/dashboard/);
  });

  await step("template downloads", async () => {
    await page.getByRole("link", { name: "Upload Products" }).click();
    await page.getByText("No uploads yet.").waitFor();
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.getByRole("button", { name: "CSV template" }).click(),
    ]);
    assert.equal(download.suggestedFilename(), "sellerscope-products.csv");
    const path = await download.path();
    assert.match(readFileSync(path, "utf8"), /ASIN,Product name,Brand/);
  });

  await step("wrong file type is refused before upload", async () => {
    await page.getByLabel("Product file").setInputFiles(txtPath);
    await page.getByText("Upload a .csv or .xlsx file.").waitFor();
  });

  let batchUrl;
  await step("upload, background processing, preview", async () => {
    await page.getByLabel("Product file").setInputFiles(csvPath);
    await page.waitForURL(/\/upload\/[0-9a-f-]{36}$/);
    batchUrl = page.url();
    await page.getByText("Ready to review").waitFor({ timeout: 60_000 }); // parsed by the worker
    const stat = (label) => page.locator("div.rounded-lg", { hasText: label }).locator("div.text-2xl");
    assert.equal(await stat("Rows in file").textContent(), "7");
    assert.equal(await stat("Ready to add").textContent(), "3");
    assert.equal(await stat("Invalid").textContent(), "3");
    assert.equal(await stat("Duplicates in file").textContent(), "1");
    await page.getByRole("cell", { name: "B0UPE2E002", exact: true }).waitFor(); // extracted from URL
    await shot(page, "14-upload-preview");
  });

  await step("rejected rows explain why", async () => {
    await page.getByRole("tab", { name: /^Invalid/ }).click();
    await page.getByText("Flipkart is not supported yet (Amazon.in only).").waitFor();
    await page.getByText("No ASIN in this row.").waitFor();
    await page.getByRole("tab", { name: /^Duplicate in file/ }).click();
    await page.getByText("Same ASIN as row 2; only the first occurrence is added.").waitFor();
    await shot(page, "15-upload-rejected");
  });

  await step("rejected-rows CSV download is formula-safe", async () => {
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.getByRole("button", { name: "Download rejected rows (CSV)" }).click(),
    ]);
    assert.match(download.suggestedFilename(), /-rejected\.csv$/);
    const text = readFileSync(await download.path(), "utf8");
    assert.match(text, /Flipkart is not supported/);
    assert.match(text, /'=HYPERLINK/);
    assert.doesNotMatch(text, /(^|,)=HYPERLINK/m);
  });

  await step("commit adds the valid products", async () => {
    await page.getByRole("button", { name: "Add 3 product(s)" }).click();
    await page.getByText("Added 3 product(s).").waitFor();
    await page.getByRole("link", { name: "View in Product Mapping" }).click();
    await page.getByText("1–3 of 3").waitFor();
    for (const asin of ["B0UPE2E001", "B0UPE2E002", "B0UPE2E004"]) {
      await page.getByRole("cell", { name: asin, exact: true }).waitFor();
    }
  });

  await step("history shows the upload", async () => {
    await page.getByRole("link", { name: "Upload Products" }).click();
    const row = page.locator("tr", { hasText: `catalog-${run}.csv` });
    await row.getByText("Added").waitFor();
    assert.equal(await row.locator("td").nth(4).textContent(), "3");
    await shot(page, "16-upload-history");
  });

  await step("a file without an ASIN column fails with a clear reason", async () => {
    await page.getByLabel("Product file").setInputFiles(badPath);
    await page.waitForURL(/\/upload\/[0-9a-f-]{36}$/);
    await page.getByText("This file couldn't be processed.").waitFor({ timeout: 60_000 });
    await page.getByText("No ASIN column found.").waitFor();
  });

  await step("reopening a committed upload keeps its results", async () => {
    await page.goto(batchUrl);
    await page.getByText("Added 3 product(s).").waitFor();
    assert.equal(await page.getByRole("button", { name: /Add .* product/ }).count(), 0);
  });

  console.log(`\n${steps.length} upload e2e steps passed`);
} catch (err) {
  await shot(page, "zz-uploads-failure");
  console.error(`\nFAILED after ${steps.length} steps:`, err);
  process.exitCode = 1;
} finally {
  await browser.close();
}

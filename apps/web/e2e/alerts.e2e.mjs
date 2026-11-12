// End-to-end: alert rules, alerts raised by real (MOCK) scans in the Celery worker, the email
// digest sent by the worker's alerts queue, and triage in the inbox (M10).
// MOCK listings drift every MOCK_EPOCH_SECONDS (5s in run-local.sh), so a rescan finds new sellers.
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { join } from "node:path";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");

const BASE = process.env.E2E_BASE_URL ?? "http://localhost:3100";
const API = process.env.E2E_API_URL ?? "http://localhost:8000/api/v1";
const AUTH = process.env.E2E_AUTH_URL ?? "http://127.0.0.1:9999/auth/v1";
const MAILDIR = process.env.E2E_MAILDIR;
const SHOTS = process.env.E2E_SCREENSHOTS;
const run = Date.now().toString(36);
const user = { email: `alerts-${run}@example.com`, password: "alerts-pass-1" };
const ASINS = ["B0VICTIM01", "B0VICTIM02", "B0VICTIM03"]; // multi-seller MOCK listings

const shot = async (page, name) => SHOTS && page.screenshot({ path: join(SHOTS, `${name}.png`), fullPage: true });
const steps = [];
const step = async (name, fn) => {
  await fn();
  steps.push(name);
  console.log(`  ✓ ${name}`);
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function alertEmails(to) {
  const dir = join(MAILDIR, "new");
  return readdirSync(dir)
    .map((f) => readFileSync(join(dir, f), "utf8").replace(/=\r?\n/g, "").replace(/=([0-9A-F]{2})/g, (_, h) => String.fromCharCode(parseInt(h, 16))))
    .filter((raw) => raw.includes(`To: ${to}`) && raw.includes("Subject: [SellerScope]"));
}

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
  await step("sign up and add products", async () => {
    await page.goto(`${BASE}/register`);
    await page.getByLabel("Work email").fill(user.email);
    await page.getByLabel("Password").fill(user.password);
    await page.getByRole("button", { name: "Create account" }).click();
    await page.waitForURL(/\/onboarding/);
    await page.getByLabel("Organization name").fill("Alerts Co");
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
        body: JSON.stringify({ identifier: asin, product_name: `Product ${asin.slice(-2)}`, brand_name: "Alerts" }),
      });
      assert.equal(r.status, 201, await r.text());
    }
  });

  await step("create a 'new seller' rule that emails me", async () => {
    await page.getByRole("link", { name: "Alerts" }).click();
    await page.getByText("Nothing needs attention.").waitFor();
    await page.getByRole("tab", { name: "Rules" }).click();
    await page.getByText("No alert rules yet.").waitFor();
    await page.getByRole("button", { name: "New rule" }).click();
    const dialog = page.getByRole("dialog", { name: "New alert rule" });
    await dialog.getByLabel("Alert when").selectOption("new_seller");
    await dialog.getByLabel("Also email these members").check();
    await dialog.getByLabel(user.email).check();
    await dialog.getByRole("button", { name: "Create rule" }).click();
    await dialog.waitFor({ state: "hidden" });
    const row = page.locator("tr", { hasText: "New seller" });
    await row.getByText("In app + email (1)").waitFor();
    await row.getByText("Any new seller").waitFor();
  });

  await step("rule form validates; create a 'too many sellers' rule", async () => {
    await page.getByRole("button", { name: "New rule" }).click();
    const dialog = page.getByRole("dialog", { name: "New alert rule" });
    await dialog.getByLabel("Alert when").selectOption("seller_count_above");
    await dialog.getByLabel("Also email these members").check(); // no recipient chosen
    await dialog.getByLabel("Alert above this many sellers").fill("1");
    await dialog.getByRole("button", { name: "Create rule" }).click();
    await dialog.getByRole("alert").getByText(/at least one email recipient/).waitFor();
    await dialog.getByLabel("Also email these members").uncheck();
    await dialog.getByRole("button", { name: "Create rule" }).click();
    await dialog.waitFor({ state: "hidden" });
    await page.locator("tr", { hasText: "Too many sellers" }).getByText("More than 1 seller").waitFor();
    await shot(page, "30-alert-rules");
  });

  await step("first scan: threshold rule fires, change rules wait for a baseline", async () => {
    await scanAll();
    await page.getByRole("link", { name: /^Alerts/ }).click();
    await page.getByText(/^B0VICTIM0\d has \d+ sellers \(limit 1\)$/).first().waitFor();
    assert.equal(await page.getByText(/^New seller on /).count(), 0);
    // Open-alert badge in the navigation.
    await page.getByRole("link", { name: /Alerts\s*\d+ open alerts/ }).waitFor();
  });

  await step("rescan after listings drift: new-seller alerts, emailed by the worker", async () => {
    await sleep(6_000);
    await scanAll();
    await page.goto(`${BASE}/alerts`);
    await page.getByText(/^New seller on B0VICTIM0\d: MOCK\d{4}$/).first().waitFor();
    let emails = [];
    for (let i = 0; i < 30 && emails.length === 0; i++) {
      emails = alertEmails(user.email);
      if (emails.length === 0) await sleep(1_000);
    }
    // One digest per worker run (a job split across runs may send more than one).
    assert.ok(emails.length >= 1, "a digest email was sent");
    assert.match(emails[0], /New seller on B0VICTIM0\d: MOCK\d{4}/);
    assert.match(emails[0], /\/alerts\?alert=[0-9a-f-]{36}/);
    assert.doesNotMatch(emails[0], /sellers \(limit 1\)/, "the threshold rule has email off");
    await page.reload();
    await page.getByText(/^Emailed to 1$/).first().waitFor();
    await shot(page, "31-alerts-inbox");
  });

  await step("acknowledge, resolve and filter", async () => {
    const first = page.getByRole("list", { name: "Alerts" }).getByRole("listitem").first();
    const title = await first.locator("[data-alert-title]").textContent();
    await first.getByRole("button", { name: "Acknowledge" }).click();
    const item = page.getByRole("listitem").filter({ hasText: title });
    await item.getByText(/Acknowledged /).waitFor();
    await item.getByRole("button", { name: "Resolve" }).click();
    await page.getByLabel("Status").selectOption("resolved");
    await page.getByRole("listitem").filter({ hasText: title }).getByText(/Resolved \d/).waitFor();
    await page.getByLabel("Status").selectOption("open");
    assert.equal(await page.getByRole("listitem").filter({ hasText: title }).count(), 0);
  });

  await step("bulk acknowledge selected alerts", async () => {
    const boxes = page.getByRole("checkbox", { name: /^Select: / });
    await boxes.first().waitFor();
    const before = await boxes.count();
    await boxes.nth(0).check();
    if (before > 1) await boxes.nth(1).check();
    await page.getByText(/^\d+ selected$/).waitFor();
    await page.getByRole("button", { name: "Acknowledge", exact: true }).first().click();
    await page.getByText(/^\d+ selected$/).waitFor({ state: "hidden" });
    await page.waitForFunction(
      (n) => document.querySelectorAll('input[aria-label^="Select: "]').length === n,
      before - Math.min(before, 2),
    );
  });

  await step("disable a rule; dashboard shows open alerts", async () => {
    await page.getByRole("tab", { name: "Rules" }).click();
    const toggle = page.getByLabel("Enable Too many sellers");
    await toggle.uncheck();
    await page.locator("tr", { hasText: "Too many sellers" }).getByText("Off").waitFor();
    await page.getByRole("link", { name: "Dashboard" }).click();
    const tile = page.locator("div.rounded-lg", { hasText: "Open alerts" });
    const value = await tile.locator("div.text-3xl").textContent({ timeout: 30_000 });
    assert.ok(Number(value) >= 1, `open alerts: ${value}`);
  });

  await step("mobile layout of the inbox", async () => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`${BASE}/alerts`);
    await page.getByRole("list", { name: "Alerts" }).waitFor();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
    assert.equal(overflow, false, "no horizontal scroll on phones");
    await shot(page, "32-alerts-mobile");
  });

  console.log(`\n${steps.length} alerts e2e steps passed`);
} catch (err) {
  await shot(page, "zz-alerts-failure");
  console.error(`\nFAILED after ${steps.length} steps:`, err);
  process.exitCode = 1;
} finally {
  await browser.close();
}

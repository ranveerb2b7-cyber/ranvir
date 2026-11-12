// End-to-end: sign-up, onboarding, invitations, roles, org switching, sign-out.
// Runs against a live stack (see e2e/README.md). Uses the preinstalled Playwright.
//
// Env: E2E_BASE_URL (web), E2E_MAILDIR (Maildir written by the SMTP sink), E2E_SCREENSHOTS (dir)
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { createRequire } from "node:module";
import { join } from "node:path";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");

const BASE = process.env.E2E_BASE_URL ?? "http://localhost:3100";
const MAILDIR = process.env.E2E_MAILDIR;
const SHOTS = process.env.E2E_SCREENSHOTS;
const run = Date.now().toString(36);
const owner = { email: `owner-${run}@example.com`, password: "correct-horse-1" };
const invitee = { email: `analyst-${run}@example.com`, password: "battery-staple-2" };

function latestInviteLink(to) {
  const dir = join(MAILDIR, "new");
  const files = readdirSync(dir)
    .map((f) => join(dir, f))
    .sort((a, b) => statSync(b).mtimeMs - statSync(a).mtimeMs);
  for (const file of files) {
    const raw = readFileSync(file, "utf8");
    if (raw.includes(`To: ${to}`)) {
      // Bodies may be quoted-printable: undo soft line breaks and =XX escapes.
      const body = raw
        .replace(/=\r?\n/g, "")
        .replace(/=([0-9A-F]{2})/g, (_, hex) => String.fromCharCode(parseInt(hex, 16)));
      const match = body.match(/(http\S+\/accept-invite\?token=[\w%-]+)/);
      if (match) return match[1];
    }
  }
  throw new Error(`No invitation email for ${to}`);
}

async function shot(page, name) {
  if (SHOTS) await page.screenshot({ path: join(SHOTS, `${name}.png`), fullPage: true });
}

async function register(page, user) {
  await page.getByRole("link", { name: "Create an account" }).click();
  await page.getByLabel("Work email").fill(user.email);
  await page.getByLabel("Password").fill(user.password);
  await page.getByRole("button", { name: "Create account" }).click();
}

async function signOut(page) {
  await page.getByRole("button", { name: "Sign out" }).click();
  await page.waitForURL(/\/login/);
}

const steps = [];
const step = async (name, fn) => {
  await fn();
  steps.push(name);
  console.log(`  ✓ ${name}`);
};

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
page.on("pageerror", (e) => console.error("page error:", e.message));

try {
  await step("signed-out users are redirected to sign-in", async () => {
    await page.goto(`${BASE}/team`);
    await page.waitForURL(/\/login\?next=%2Fteam/);
    await shot(page, "01-login");
  });

  await step("pages carry a nonce-based Content Security Policy", async () => {
    const violations = [];
    page.on("console", (m) => /Content.Security.Policy/i.test(m.text()) && violations.push(m.text()));
    const first = await page.goto(`${BASE}/login`);
    const csp = first.headers()["content-security-policy"] ?? "";
    assert.match(csp, /script-src 'self' 'nonce-[A-Za-z0-9+/=]+' 'strict-dynamic'/);
    assert.ok(!/script-src[^;]*'unsafe-inline'/.test(csp), csp);
    assert.match(csp, /frame-ancestors 'none'/);
    const second = await page.goto(`${BASE}/login`);
    assert.notEqual(second.headers()["content-security-policy"], csp, "a fresh nonce per request");
    await page.getByRole("button", { name: "Sign in" }).waitFor(); // hydrated: scripts allowed
    assert.deepEqual(violations, []);
  });

  await step("register and land on onboarding", async () => {
    await page.goto(`${BASE}/login`);
    await register(page, owner);
    await page.waitForURL(/\/onboarding/);
    await shot(page, "02-onboarding");
  });

  await step("create organization and reach the dashboard", async () => {
    await page.getByLabel("Organization name").fill("Acme Brands");
    await page.getByRole("button", { name: "Create organization" }).click();
    await page.waitForURL(/\/dashboard/);
    await page.getByText("Acme Brands").first().waitFor();
    await page.getByText("Owner", { exact: true }).waitFor();
    await shot(page, "03-dashboard");
  });

  await step("owner invites an analyst (email delivered)", async () => {
    await page.getByRole("link", { name: "Team Management" }).click();
    await page.getByLabel("Invite by email").fill(invitee.email);
    await page.getByLabel("Role", { exact: true }).selectOption("analyst");
    await page.getByRole("button", { name: "Send invite" }).click();
    await page.getByText(`Invitation sent to ${invitee.email}.`).waitFor();
    await page.getByRole("heading", { name: "Pending invitations" }).waitFor();
    assert.ok(await page.getByText(invitee.email).first().isVisible());
    await shot(page, "04-team-invited");
  });

  const link = latestInviteLink(invitee.email);
  assert.ok(link.startsWith(BASE), `invite link should point at the web app: ${link}`);

  await step("invitee opens the link, registers and accepts", async () => {
    await signOut(page);
    await page.goto(link);
    await page.waitForURL(/\/login\?next=/);
    await register(page, invitee);
    await page.waitForURL(/\/accept-invite\?token=/);
    await page.getByRole("heading", { name: "Join Acme Brands" }).waitFor();
    await page.getByText("You were invited as").waitFor();
    await shot(page, "05-accept-invite");
    await page.getByRole("button", { name: "Accept invitation" }).click();
    await page.waitForURL(/\/dashboard/);
    await page.getByText("Analyst", { exact: true }).waitFor();
  });

  await step("analyst sees the team read-only", async () => {
    await page.getByRole("link", { name: "Team Management" }).click();
    await page.getByText(owner.email).waitFor();
    assert.equal(await page.getByLabel("Invite by email").count(), 0);
    assert.equal(await page.getByRole("button", { name: "Remove" }).count(), 0);
    await shot(page, "06-team-analyst");
  });

  await step("the used invitation link cannot be reused", async () => {
    await page.goto(link);
    await page.getByText("This invitation has already been used.").waitFor();
  });

  await step("owner demotes the analyst to viewer", async () => {
    await page.goto(`${BASE}/dashboard`);
    await signOut(page);
    await page.getByLabel("Email").fill(owner.email);
    await page.getByLabel("Password").fill(owner.password);
    await page.getByRole("button", { name: "Sign in" }).click();
    await page.waitForURL(/\/dashboard/);
    await page.getByRole("link", { name: "Team Management" }).click();
    await page.getByLabel(`Role for ${invitee.email}`).selectOption("viewer");
    await page.getByText(`Updated ${invitee.email}.`).waitFor();
  });

  await step("owner creates a second organization and switches between them", async () => {
    await page.goto(`${BASE}/onboarding`);
    await page.getByLabel("Organization name").fill("Second Brand");
    await page.getByRole("button", { name: "Create organization" }).click();
    await page.waitForURL(/\/dashboard/);
    const switcher = page.getByLabel("Organization");
    await switcher.waitFor();
    assert.equal(await switcher.locator("option:checked").textContent(), "Second Brand");
    await page.getByRole("link", { name: "Team Management" }).click();
    await page.getByText("People with access to Second Brand.").waitFor();
    assert.equal(await page.getByText(invitee.email).count(), 0, "other org's members must not show");
    const acmeId = await switcher.locator("option", { hasText: "Acme Brands" }).getAttribute("value");
    await switcher.selectOption(acmeId);
    await page.getByText("People with access to Acme Brands.").waitFor();
    await page.getByText(invitee.email).waitFor();
    await shot(page, "07-org-switcher");
  });

  await step("settings: rename organization", async () => {
    await page.getByRole("link", { name: "Settings" }).click();
    await page.getByLabel("Name", { exact: true }).fill("Acme Brands India");
    await page.getByRole("button", { name: "Rename" }).click();
    await page.getByText("Organization renamed.").waitFor();
    await shot(page, "08-settings");
  });

  await step("mobile layout has no horizontal scroll", async () => {
    const mobile = await browser.newPage({ viewport: { width: 375, height: 800 } });
    await mobile.context().addCookies(await page.context().cookies());
    await mobile.goto(`${BASE}/team`);
    await mobile.getByRole("heading", { name: "Team Management" }).waitFor();
    const width = await mobile.evaluate(() => document.documentElement.scrollWidth);
    assert.ok(width <= 375, `scrollWidth ${width}`);
    if (SHOTS) await mobile.screenshot({ path: join(SHOTS, "09-team-mobile.png"), fullPage: true });
    await mobile.close();
  });

  console.log(`\n${steps.length} e2e steps passed`);
} catch (err) {
  await shot(page, "zz-failure");
  console.error(`\nFAILED after ${steps.length} steps:`, err);
  process.exitCode = 1;
} finally {
  await browser.close();
}

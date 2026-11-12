// Builds the unpacked extension into dist/. Configuration is baked in at build time
// (MV3 forbids remote code): EXTENSION_API_URL and EXTENSION_WEB_URL.
import { build } from "esbuild";
import { cpSync, mkdirSync, rmSync, writeFileSync } from "node:fs";

const API_URL = process.env.EXTENSION_API_URL ?? "http://localhost:8000/api/v1";
const WEB_URL = process.env.EXTENSION_WEB_URL ?? "http://localhost:3000";
const apiOrigin = new URL(API_URL).origin;

rmSync("dist", { recursive: true, force: true });
mkdirSync("dist", { recursive: true });

await build({
  entryPoints: { popup: "src/popup/popup.ts", background: "src/background.ts" },
  outdir: "dist",
  entryNames: "[name]",
  bundle: true,
  format: "esm",
  target: "chrome120",
  minify: process.env.NODE_ENV === "production",
  define: { __API_URL__: JSON.stringify(API_URL), __WEB_URL__: JSON.stringify(WEB_URL) },
  logLevel: "warning",
});
cpSync("src/popup/popup.html", "dist/popup.html");
cpSync("src/popup/popup.css", "dist/popup.css");

const manifest = {
  manifest_version: 3,
  name: "SellerScope",
  version: "0.1.0",
  description: "See your SellerScope seller data for the Amazon.in product you're viewing.",
  action: { default_popup: "popup.html", default_title: "SellerScope" },
  background: { service_worker: "background.js", type: "module" },
  // Least privilege: storage for the token; URL access only on Amazon.in and our API.
  permissions: ["storage"],
  host_permissions: [
    "https://www.amazon.in/*",
    "https://amazon.in/*",
    "https://m.amazon.in/*",
    `${apiOrigin}/*`,
  ],
  content_security_policy: { extension_pages: "script-src 'self'; object-src 'self'" },
  minimum_chrome_version: "120",
};
writeFileSync("dist/manifest.json", JSON.stringify(manifest, null, 2) + "\n");
console.log(`extension built for API ${API_URL}, web ${WEB_URL}`);

# SellerScope Chrome extension (MV3)

Shows the seller data SellerScope has **already stored** for the Amazon.in product open in the current tab, with a "Check now" button that queues a normal scan through the official connector.

## Privacy and permissions
- **Page access:** the extension uses only the **page address (URL)**. It parses the ASIN locally (`src/lib/detect.ts`) and sends only the ASIN to the SellerScope API. It never reads or sends page content.
- **No content scripts:** nothing is injected into Amazon pages, and nothing is clicked, filled in or scraped.
- **Permissions:**
  - `storage`, for the connection token.
  - Host access to `amazon.in` (to read the tab's URL) and to the SellerScope API origin.
  - No `<all_urls>`, `tabs`, `scripting` or cookies permissions.
- **No remote code:** configuration is baked in at build time.
- **Token storage:** the token is kept in `chrome.storage.session`, which is cleared when the browser closes, unless the user ticks "Remember this browser" (then `chrome.storage.local`).

## Connecting (pairing)
1. The popup creates a PKCE verifier and opens `/extension/connect?challenge=…` in SellerScope.
2. The signed-in member approves; SellerScope shows a one-time code. The code is valid for 10 minutes, usable once, and only together with that verifier.
3. The member enters the code in the popup. The API returns a scoped token. It expires after 90 days and can be revoked in **Settings → Browser extension** or with the popup's "Disconnect".

## Build and load
```bash
pnpm install
EXTENSION_API_URL=https://api.example.com/api/v1 EXTENSION_WEB_URL=https://app.example.com pnpm extension:build
```
Load `apps/extension/dist` in `chrome://extensions` → Developer mode → "Load unpacked". The default values point at local development (`http://localhost:8000/api/v1`, `http://localhost:3000`).

## Tests
- `pnpm extension:test`: URL detection corpus and PKCE.
- `apps/web/e2e/extension.e2e.mjs`: runs the unpacked extension in Chromium against the local stack, with Amazon.in pages served by Playwright routing (`make test-e2e`).

## Before publishing to the Chrome Web Store (not done)
- Icons and listing assets.
- A privacy policy URL.
- A production build with the production API and web URLs.
- A Chrome Web Store developer account.

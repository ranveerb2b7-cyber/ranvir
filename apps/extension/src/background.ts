// Service worker: shows a badge on Amazon.in product pages. Reads only the tab URL, which
// Chrome exposes for sites listed in host_permissions; no script is injected into pages.
import { detectProduct } from "./lib/detect";

async function update(tabId: number, url: string | undefined): Promise<void> {
  const isProduct = detectProduct(url).kind === "product";
  await chrome.action.setBadgeText({ tabId, text: isProduct ? "●" : "" });
  if (isProduct) await chrome.action.setBadgeBackgroundColor({ tabId, color: "#2a58d6" });
}

chrome.tabs.onUpdated.addListener((tabId, change, tab) => {
  if (change.url || change.status === "complete") void update(tabId, tab.url);
});
chrome.tabs.onActivated.addListener(({ tabId }) => {
  void chrome.tabs.get(tabId).then((tab) => update(tabId, tab.url));
});

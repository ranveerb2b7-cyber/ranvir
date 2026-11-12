/**
 * Detects a product from a page URL. This is the ONLY page information the extension uses:
 * it never reads or sends page content (docs/plan/09 §9.7).
 * Mirrors the API's parser (apps/api/src/sellerscope/connectors/identifiers.py).
 */

export type Detection =
  | { kind: "product"; marketplace: "amazon_in"; asin: string }
  | { kind: "amazon_in_other" } // an Amazon.in page that is not a product page
  | { kind: "other_amazon" } // another Amazon country site: not supported
  | { kind: "short_link" }
  | { kind: "unsupported" };

const AMAZON_IN_HOSTS = new Set(["amazon.in", "www.amazon.in", "m.amazon.in", "smile.amazon.in"]);
const SHORT_LINK_HOSTS = new Set(["amzn.in", "amzn.to", "a.co"]);
const PATH_ASIN = /\/(?:dp|gp\/product|gp\/aw\/d|product|exec\/obidos\/asin)\/([A-Za-z0-9]{10})(?=[/?#]|$)/i;
const ASIN = /^[A-Z0-9]{10}$/;
// Amazon's other country storefronts (exact hosts, so look-alike domains don't match).
const OTHER_AMAZON =
  /^(?:www\.|m\.|smile\.)?amazon\.(?:com|ca|com\.mx|com\.br|co\.uk|de|fr|it|es|nl|se|pl|com\.be|com\.tr|ae|sa|eg|co\.jp|com\.au|sg|cn)$/;

export function detectProduct(rawUrl: string | undefined | null): Detection {
  if (!rawUrl) return { kind: "unsupported" };
  let url: URL;
  try {
    url = new URL(rawUrl);
  } catch {
    return { kind: "unsupported" };
  }
  if (url.protocol !== "https:" && url.protocol !== "http:") return { kind: "unsupported" };
  const host = url.hostname.toLowerCase();
  if (SHORT_LINK_HOSTS.has(host)) return { kind: "short_link" };
  if (!AMAZON_IN_HOSTS.has(host)) {
    return OTHER_AMAZON.test(host) ? { kind: "other_amazon" } : { kind: "unsupported" };
  }
  const match = PATH_ASIN.exec(url.pathname);
  const asin = match?.[1]?.toUpperCase();
  if (!asin || !ASIN.test(asin)) return { kind: "amazon_in_other" };
  return { kind: "product", marketplace: "amazon_in", asin };
}

import { describe, expect, it } from "vitest";

import { detectProduct } from "../src/lib/detect";

const product = (asin: string) => ({ kind: "product", marketplace: "amazon_in", asin });

describe("detectProduct: URL corpus", () => {
  it.each([
    ["https://www.amazon.in/dp/B0CHX1W1XY", "B0CHX1W1XY"],
    ["https://www.amazon.in/Steel-Water-Bottle-1L/dp/B0CHX1W1XY/ref=sr_1_3?crid=X&th=1", "B0CHX1W1XY"],
    ["https://www.amazon.in/dp/b0chx1w1xy?psc=1", "B0CHX1W1XY"],
    ["https://amazon.in/gp/product/B0CHX1W1XY", "B0CHX1W1XY"],
    ["https://m.amazon.in/gp/aw/d/B0CHX1W1XY/", "B0CHX1W1XY"],
    ["https://www.amazon.in/exec/obidos/ASIN/8172234988", "8172234988"],
    ["https://www.amazon.in/product/B0CHX1W1XY#reviews", "B0CHX1W1XY"],
    ["https://WWW.AMAZON.IN/DP/B0CHX1W1XY", "B0CHX1W1XY"],
    ["http://www.amazon.in/dp/B0CHX1W1XY", "B0CHX1W1XY"],
  ])("%s", (url, asin) => {
    expect(detectProduct(url)).toEqual(product(asin));
  });

  it.each([
    "https://www.amazon.in/",
    "https://www.amazon.in/s?k=water+bottle",
    "https://www.amazon.in/gp/cart/view.html",
    "https://www.amazon.in/dp/B0SHORT",
    "https://www.amazon.in/dp/B0CHX1W1XYZ", // 11 characters
    "https://www.amazon.in/ap/signin?openid.return_to=/dp/B0CHX1W1XY", // ASIN only in the query
    "https://www.amazon.in/hz/wishlist/ls/B0CHX1W1XY", // not a product path
  ])("Amazon.in but not a product page: %s", (url) => {
    expect(detectProduct(url).kind).toBe("amazon_in_other");
  });

  it("refuses other Amazon sites, short links and everything else", () => {
    expect(detectProduct("https://www.amazon.com/dp/B0CHX1W1XY").kind).toBe("other_amazon");
    expect(detectProduct("https://www.amazon.co.uk/dp/B0CHX1W1XY").kind).toBe("other_amazon");
    expect(detectProduct("https://amzn.in/d/1aBcDeF").kind).toBe("short_link");
    expect(detectProduct("https://amzn.to/3xyz").kind).toBe("short_link");
    for (const url of [
      "https://www.amazon.in.evil.example/dp/B0CHX1W1XY",
      "https://evil.example/www.amazon.in/dp/B0CHX1W1XY",
      "https://www.flipkart.com/p/itm123",
      "chrome://extensions",
      "file:///dp/B0CHX1W1XY",
      "not a url",
      "",
      undefined,
    ]) {
      expect(detectProduct(url).kind, String(url)).toBe("unsupported");
    }
  });
});

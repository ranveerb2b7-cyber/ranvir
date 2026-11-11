# 6. Amazon India Integration — Feasibility Report

Status: **PROPOSAL — awaiting approval.** This is based on the published Selling Partner API documentation as I know it. No live call has been made yet (no credentials). Items marked **[VERIFY]** must be confirmed in the Milestone 5 spike against current docs and a real Amazon.in account before we rely on them.

## 6.1 Verdict

**Feasible, with known limits.** The SP-API Product Pricing API can return marketplace offer data for an arbitrary ASIN on Amazon.in. That includes a total offer count and up to ~20 individual offers with seller IDs, prices and fulfilment channel. It **does not return seller names** and **does not guarantee the full offer list**. The product must present these limits honestly. They map directly onto the separate `total_offer_count`, `observed_offer_count` and `unique_seller_count` metrics.

## 6.2 Relevant endpoints

| API | Operation | Use | Documented rate (default) |
|---|---|---|---|
| Product Pricing v0 | `GET /products/pricing/v0/items/{Asin}/offers?MarketplaceId=A21TJRUUN4KGV&ItemCondition=New` (**getItemOffers**) | Primary offer source | 0.5 req/s, burst 1 **[VERIFY]** |
| Product Pricing v0 | `POST /batches/products/pricing/v0/itemOffers` (**getItemOffersBatch**) | Up to 20 ASINs per call | 0.1 req/s, burst 1 → ~2 ASINs/s effective **[VERIFY]** |
| Product Pricing v2022-05-01 | `getCompetitiveSummary` (batch of 20) | Alternative: featured offer + lowest-priced offers + reference prices. Evaluate in the spike | **[VERIFY]** |
| Catalog Items 2022-04-01 | `getCatalogItem` / `searchCatalogItems` | Verify an ASIN exists on Amazon.in; fetch title and brand | **[VERIFY]** |
| Notifications | `ANY_OFFER_CHANGED` (via SQS/EventBridge) | Near-real-time changes. Only for ASINs the **authorizing seller** has listed, so it's an optional enhancement, not the core | |
| Sellers | `getMarketplaceParticipations` | Confirm the connected account participates in Amazon.in | |

- **Regional endpoint:** Amazon.in is served by `https://sellingpartnerapi-eu.amazon.com`, with LWA token endpoint `https://api.amazon.com/auth/o2/token`. Marketplace ID: `A21TJRUUN4KGV`.
- **Auth:** Login with Amazon (LWA) refresh token → access token (1 h). AWS SigV4/IAM signing is no longer required for SP-API calls **[VERIFY]**.

## 6.3 What getItemOffers gives us

| Field (response) | Maps to | Notes |
|---|---|---|
| `Summary.TotalOfferCount` | `total_offer_count` | Marketplace-reported count for the requested condition |
| `Summary.NumberOfOffers[]` (by condition × fulfillment channel) | breakdown stored in `scan_results` | Parsed as specified (the "NumberOfOffers" requirement) |
| `Summary.LowestPrices[]`, `BuyBoxPrices[]` | lowest price by channel, buy box price | |
| `Offers[]` (up to 20 **[VERIFY]**) | `product_offers` rows; `observed_offer_count = len(Offers)` | The list is a subset when TotalOfferCount > 20 |
| `Offers[].SellerId` | `seller_profiles.external_seller_id` | Opaque merchant token |
| `ListingPrice`, `Shipping` | prices (INR) | landed = listing + shipping |
| `IsFulfilledByAmazon` | `fulfilment_channel` amazon/merchant | |
| `IsBuyBoxWinner`, `IsFeaturedMerchant`, `PrimeInformation` | booleans | |
| `SellerFeedbackRating` | rating %, count | |
| `ShipsFrom`, `ShippingTime`, `SubCondition` | stored | |

### Not available from SP-API
- **Seller display names.** Only `SellerId` is returned. We'll show the seller ID with a link to the public storefront URL (`https://www.amazon.in/sp?seller=<id>`) for the user to open themselves. Users can also label sellers manually (e.g. "Authorized distributor X"). We will **not** fetch storefront pages server-side, since that would be scraping. Limitation code: `SELLER_NAME_NOT_PROVIDED`.
- **The complete offer list** when the total is above the cap. Limitation code: `OFFER_LIST_TRUNCATED`.
- **Stock quantity** per seller.
- **Used/refurbished offers** in the same call (one `ItemCondition` per call). We'll default to `New`, and other conditions are configurable at extra rate-limit cost.

## 6.4 Access model and credentials (decision needed)

SP-API calls are always made **on behalf of an authorizing Amazon seller account** (a selling partner), using our registered developer application.

| Option | How it works | Pros | Cons |
|---|---|---|---|
| **A. Each customer connects their own Amazon.in seller account via OAuth (recommended)** | SellerScope registers as a public SP-API developer with an Appstore listing. The customer clicks "Connect Amazon" → Seller Central consent → we store their encrypted refresh token | Rate limits are per customer; data use is tied to the customer's own business; the cleanest compliance story | Customer must have an Amazon.in **seller** account. Public app registration plus Amazon's review / Data Protection Policy assessment take time |
| B. Customer self-authorizes a private app and pastes credentials | Customer creates their own private SP-API app and gives us LWA client ID/secret + refresh token | No Appstore listing needed; good for pilot customers | Clunky onboarding; we hold more sensitive secrets |
| C. SellerScope's own seller account queries for all tenants | One credential serves everyone | Simple | **Not recommended.** Likely conflicts with the SP-API Acceptable Use Policy (data used for parties other than the authorizing seller); one shared rate limit across all customers |

**Recommendation:** Support **B for the pilot**, and build **A** in parallel because it needs Amazon approval. Do not ship C.

**Open question for you:** do target customers (brand owners) generally have Amazon.in Seller Central accounts? Brands that sell only via Vendor Central (1P) may not have Product Pricing API access through a vendor account **[VERIFY]**. That would block them under options A and B.

### Credentials you'll need to provide
1. An Amazon.in Seller Central account (Professional plan) to register as a developer.
2. SP-API developer registration, requesting the **Pricing** role (and **Product Listing** for catalog verification).
3. An LWA client ID + client secret for the SellerScope app. These are stored as server secrets, never in the frontend.
4. For each pilot customer: a refresh token (option B), or completion of OAuth (option A, with a redirect URI on our domain).

## 6.5 Throughput (planning numbers, to be verified)

Per connected seller account, at default rates:

| Products | getItemOffers (0.5/s) | getItemOffersBatch (20 per call at 0.1/s) |
|---|---|---|
| 1,000 | ~33 min | ~8 min |
| 10,000 | ~5.6 h | ~1.4 h |
| 50,000 | ~28 h | ~7 h |

**Implications:**
- Use batch mode by default.
- Daily monitoring is realistic up to ~50k ASINs per account. Plans must cap products × frequency accordingly.
- Workers read `x-amzn-RateLimit-Limit` and adapt.

## 6.6 Compliance notes (needs legal review before public launch)

- The SP-API **Acceptable Use Policy** and **Data Protection Policy** govern how the data may be used, stored and shared. In particular:
  - data must only be used for the authorizing seller's own business purposes
  - data must be encrypted at rest and in transit, with access controls, audit logs and an incident response plan
  - Amazon may audit
- The "monitor unauthorized sellers of my brand" use case should be described accurately in the app registration. **A lawyer should review the AUP against this product before public launch.**
- Retain raw payloads only as long as needed. Delete on disconnect according to DPP requirements.
- We won't scrape amazon.in pages server-side, and the extension won't extract page data (see Security).

## 6.7 Spike plan (part of Milestone 5)

1. Call getItemOffers and getItemOffersBatch for ~20 real ASINs (single-seller, multi-seller, >20 sellers, invalid, out-of-stock).
2. Record and scrub fixtures.
3. Confirm: rate limits, offer cap, TotalOfferCount semantics, error shapes.
4. Compare getCompetitiveSummary against getItemOffers coverage.
5. Update this report and `docs/connectors/amazon.md` with the confirmed findings.

# 7. Flipkart Integration — Feasibility Report

Status: **PROPOSAL — awaiting approval.** This is based on publicly documented Flipkart programs as I know them. Flipkart's partner documentation is partly gated behind registration. Items marked **[VERIFY]** must be confirmed with real partner access and, ideally, in writing from Flipkart.

## 7.1 Verdict

**Competitor offer-level data (all sellers for an FSN) is NOT available through any authorized Flipkart API that I'm aware of.** The SellerScope Flipkart module therefore cannot promise seller counts for Flipkart at launch. It can support FSN management, format validation, the seller's **own** listing data, and, if Flipkart grants access, limited single-offer data. Full Flipkart seller mapping would require a **data agreement with Flipkart** or another authorized source.

## 7.2 Authorized access routes evaluated

| Route | What it provides | Competitor sellers per FSN? | Status |
|---|---|---|---|
| **Flipkart Marketplace Seller APIs** (`api.flipkart.net/sellers`, OAuth2 client-credentials; self-access app or registered third-party app) | The authenticated seller's **own** listings (by SKU/FSN), inventory, price, orders, shipments, returns | **No.** Scoped to the seller's own listings | Available to Flipkart sellers **[VERIFY current versions]** |
| **Flipkart Affiliate API** (`affiliate-api.flipkart.net`) | Product search/feeds, product details by product ID: title, MRP, selling price, stock, and in some versions the **featured seller's name and rating** | **No.** At most the single featured/default seller, not all offers | Affiliate onboarding has been restricted at times; usage terms are tied to affiliate promotion, so monitoring use may breach them **[VERIFY]** |
| **Flipkart brand protection / IP programs** | Infringement reporting workflows | No API for offer lists **[VERIFY]** | Manual |
| **Direct data partnership with Flipkart** | Potentially anything Flipkart agrees to | Possibly | Business development, not engineering |
| **Licensed third-party data providers** | Varies | Possibly | Only if the provider can show it is licensed by Flipkart. Otherwise this is laundered scraping and is excluded |
| Scraping flipkart.com / mobile API reverse-engineering | — | — | **Excluded.** Violates Flipkart Terms of Use, may bypass access controls, and is prohibited by this project's rules |

## 7.3 What we will implement

1. **`FlipkartConnector` with honest capabilities:**
   ```
   total_offer_count=False, offer_list=False, seller_id=False, seller_name=False,
   price=depends_on_route, identifier_existence_check=depends_on_route
   ```
   Every Flipkart scan result is stored with `status="unavailable"` and limitation `COMPETITOR_OFFERS_NOT_AVAILABLE_VIA_AUTHORIZED_API`. The UI shows "Not available — Flipkart does not provide competitor seller data through authorized APIs" rather than `0`.
2. **FSN format validation:**
   - 16 characters, uppercase alphanumeric.
   - Commonly a 3-letter category prefix + 13 characters. This pattern is used as a warning, not a hard reject, until it is validated against real data **[VERIFY]**.
   - Extraction from URLs via the `pid=` query parameter.
   - Validated FSNs are labelled `format_valid`. They're never shown as `verified` unless an authorized source confirmed them.
3. **Seller API sub-connector (optional, once credentials exist):** for brands that are themselves Flipkart sellers. It shows their own listing status and price for an FSN, labelled as "your listing", never as competitor data.
4. **Affiliate sub-connector (only if access is granted and the terms permit this use):** featured price, stock, and featured seller name. This is stored as `observed_offer_count = 1`, `total_offer_count = null`, `is_offer_list_truncated = null`, with limitation `ONLY_FEATURED_OFFER`.
5. **A pluggable slot for a future licensed source.** The interface is ready, so adding a partner feed later means writing a new connector class, not reworking the scanning engine.

## 7.4 The Chrome extension on Flipkart

The extension detects the FSN from the URL and shows stored data. It **won't** read seller lists from the page DOM by default. Reading data the user sees in their own browser is legally different from server-side scraping, but systematic extraction is still restricted by Flipkart's Terms of Use. A "user-captured observation" feature (the user explicitly captures what's on screen, stored with `data_source = "user_observed"` and lower confidence) is listed as a **possible future feature that needs legal sign-off**. It is not in the plan.

## 7.5 Credentials and decisions needed from you

1. Do you or your pilot customers have **Flipkart seller accounts**? If so, an app ID and secret for the Seller API, for own-listing data.
2. Do you have, or can you apply for, **Flipkart Affiliate API** access? Please share the current terms so they can be reviewed.
3. Is there appetite to pursue a **direct data agreement with Flipkart**? Without one, Flipkart seller counting stays out of scope, and the marketing material must say so.

## 7.6 Required product messaging

The application, README and sales material must not claim Flipkart seller mapping coverage until an authorized source provides it. The dashboard shows a per-marketplace coverage note sourced from connector capabilities.

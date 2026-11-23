# Smart Receipt Scanner API

The backend container includes local Tesseract with Bulgarian and English language data. For a Debian or Ubuntu installation outside Docker, install `tesseract-ocr`, `tesseract-ocr-bul`, and `tesseract-ocr-eng` and run Django migrations. The scanner returns HTTP 503 if local OCR is unavailable.

All endpoints require FinDash authentication.

| Method and path | Request and result |
| --- | --- |
| `POST /api/receipts/preview/` | Multipart `file` (JPEG, PNG, WebP or HEIC/HEIF on supported platforms). Repeat the field in reading order for up to three images of the same receipt, with a combined limit of 8 MiB and up to 16 megapixels per image. Optional fields are `source` (camera, gallery or upload), `date_order` (DMY by default, or MDY) and `allow_ai` (literal `true` or `false`, defaults to `false`). Returns a proposed receipt and a one-hour account-bound token. An exact previously confirmed upload returns `duplicate_id` instead. |
| `POST /api/receipts/confirm/` | JSON combining the preview token with reviewed receipt fields and items. Returns 201 for a new receipt or 200 with an existing receipt when the image or purchase fingerprint matches. |
| `GET /api/receipts/` | Paginated confirmed receipts. Optional `store`, `product`, `start`, and `end` filters use inclusive Sofia calendar dates. |
| `GET /api/receipts/statistics/` | Net product and category spending, printed totals, and linked receipt counts, grouped by original currency. Accepts the same filters as history. |
| `GET /api/receipts/{id}/` | Confirmed receipt and items. |
| `PATCH /api/receipts/{id}/` | Correct receipt fields and optionally replace its reviewed item list atomically. A change to the currency or amount removes an incompatible payment link. |
| `GET /api/receipts/{id}/reconciliation/` | Suggest owner-scoped payments with matching signed amount and currency within three calendar days, ranked by merchant similarity and date. |
| `DELETE /api/receipts/{id}/` | Deletes the receipt and its items. The linked payment remains in the ledger. |
| `PATCH /api/receipts/{id}/reconciliation/` | Send `{"transaction": 123}` to link an existing owner-scoped payment or `{"transaction": null}` to unlink. |

Confirm with the merchant, purchase timestamp (prefer ISO 8601 with offset), original EUR or BGN currency, signed final total, and at least one reviewed item. Each item needs its original description and signed line total. A product ID optionally refers to an existing grocery catalog entry. Monetary inputs use decimal strings. Purchases use positive receipt totals and refunds use negative receipt totals. OCR suggestions depend on the layout and clarity of the image. Missing fields and suggested values require review.

Reconciliation requires matching currency and the opposite transaction sign, since the ledger represents expenses as negative amounts. A bank payment can link to one receipt. The user chooses the payment, and the link never creates or updates a transaction. Existing spending analytics continue to read the transaction ledger, so receipt line items simply provide item-level detail. The API reports if a link no longer matches after an edit to the transaction.

The preview uses null for missing values. If OCR reads only the date, `purchase_date` is returned and `purchased_at` remains null. `totals_check` reports whether the signed, extracted line totals add up to the printed total. A mismatch can reflect omitted rows, receipt-wide discounts, tax, or OCR errors. `possible_duplicate_ids` contains up to five receipts with the same merchant, amount, currency and date. These are suggestions for review.

Images and OCR text are processed in memory and discarded after the request. With explicit `allow_ai=true`, FinDash can send filtered OCR lines to Gemini to identify the merchant and pair split item descriptions with printed prices. Image pixels are never sent. Suggestions are checked against the OCR lines, and provider failures fall back to local results with an `ai_status` of `unavailable`. The API key stays on the server. Confirmed structured data and duplicate-detection hashes are retained until receipt deletion. Keep request bodies out of proxy and application logs and serve this API over HTTPS.


Open **Receipt history and spending** from the scanner, or visit `/receipts/history`. Search by store, product, or date to filter the saved receipts and receipt statistics. A product search selects receipts containing the product. Breakdowns include all items from those receipts. Signed refunds reduce product and category totals. Printed receipt totals and item totals are displayed separately because taxes, discounts, and incomplete item details can create differences. Receipt statistics are a separate view of purchases and should never be added to bank-ledger totals. All suggestions require an explicit link action.

## My Products

Open **More → My Products** or visit `/my-products`. Save products by name or favorite a catalog offer. Matching advertised offers honor the selected supermarkets, category interests, package, brand, and configured discount threshold. An unknown discount cannot satisfy a configured threshold. Excluded or muted products are suppressed.

Receipt personalization is opt-in. It suggests recognized staples purchased on at least three distinct days in the last 180 days. Approve or reject each suggestion. Turning personalization off stops receipt analysis and preserves prior decisions. Clearing inferred preferences removes those decisions while keeping receipts and manual products. If personalization remains on, the same receipt evidence can produce new suggestions.

Deal alerts require both **Enable in-app deal alerts** in Shopping settings and **Allow deal alerts** on each product. The Grocery deals category in Notification settings can also suppress alerts. Choose individual alerts or one daily digest and set optional quiet hours. Delivery times follow the account timezone. Alerts use current public promotions at preferred stores. Membership-only prices are excluded from delivery.

Each alert lists the advertised product, retailer, package price, expiration, and reason. Favorites, same-currency package price thresholds, and an optional historical unit-price comparison can trigger alerts. Receipt comparison requires the separate receipt-personalization opt-in and a comparable confirmed purchase from the last 180 days. FinDash requires at least a 10% unit-price difference for that reason. Track a specific current offer to receive a separate expiry reminder within 24 hours. A daily digest includes up to ten current deals and is sent once per account day. Offers skipped during quiet hours or after a digest are reevaluated at the next eligible check.

Successful catalog refreshes enqueue reevaluation after commit. The existing Celery worker and beat schedule also reevaluate deals every 15 minutes by default. Run `manage.py shell -c 'from api.tasks import schedule_grocery_deals; schedule_grocery_deals.delay()'` to enqueue a check with a worker running. Receipt data and preferences stay in FinDash. Retailer integrations fetch public offers without sending user preferences.

Authenticated endpoints are rooted at `/api/grocery/my-products/`. GET returns the library, settings, suggestions, and matching offers. POST adds a manual product. PATCH or DELETE `{id}/` edits or removes it. PATCH `settings/` updates personalization controls. POST `suggestions/` accepts `normalized_name` and an `approve` or `reject` decision, and DELETE `suggestions/` clears inferred preferences. POST `{id}/tracked-offers/` with `{"offer_id": 123}` tracks a current offer. DELETE `{id}/tracked-offers/{offer_id}/` stops tracking it.

### Personalized deals API

`GET /api/grocery/personalized-deals/` ranks current advertised offers for saved product preferences, grouped by product. The manual library sorts ahead of receipt-approved interests. Each group separates verified matches from optional review candidates. Exact matches require documented product and package evidence. A score is a ranking signal based on catalog evidence, not a probability of availability.

- Set `currency=EUR` (default) or `currency=BGN`. Prices are compared within the requested currency and measurement unit.
- Repeat `membership_retailers` for stores whose membership prices you want included. Membership prices are excluded by default and remain labeled when included.
- Set `include_review=true` to see uncertain alternatives. Incompatible products, expired or stale offers, and offers without usable advertised prices or package data are excluded.
- If receipt personalization is on, a comparable confirmed receipt may supply a historical price per kg or liter. FinDash sends no savings claim. Retailer coverage depends on the catalog’s last successful refresh.

`PUT /api/grocery/personalized-deals/{preference_id}/offers/{offer_id}/review/` accepts `{"decision":"accept"}` for an uncertain candidate or `{"decision":"reject"}` to hide a match. Accepted candidates remain comparable. Send DELETE to the same path to undo either correction. Decisions are private and rechecked when product evidence changes.


### My Deals dashboard

Open **More → My Deals** or visit `/my-deals`. Promotions and the Grocery Optimizer also link to the dashboard. It shows matching offers, lower-than-receipt unit prices, expiring offers, and candidates for review. Price comparisons show the prior confirmed receipt date and price, and describe the difference per unit. An advertised percentage is shown separately when the retailer publishes it.

Catalog badges distinguish current, stale, and unavailable retailer data. Offers are omitted when their catalog snapshot is stale. **Add to shopping list** rechecks the selected catalog package on the server, then adds the product and package quantity to the account's draft list for the current browser tab. The optimizer calculates its own current prices when comparing the basket.

The deals response includes image and expiration metadata, retailer catalog status, and the difference between the historical and current unit prices where available. `GET /api/grocery/catalog/{id}/` validates a catalog package for the optimizer handoff, including advertised price, expiry, and public eligibility.

### Household shopping lists

From Grocery basket, create a shared list or enable sharing on a saved list. A list remains accessible only to its owner until a registered FinDash user accepts an invitation. The owner can invite and remove members or delete the list. Accepted members can add and remove products, change quantities, mark purchases, and optimize unpurchased items. Product lines show who added and completed them. Only this shopping list and its optimizer settings are shared.

The shared list polls while visible. Server-side revocation applies to subsequent reads and writes immediately. Items carry a revision, and a conflicting edit or removal returns HTTP 409. Reload the changed item before retrying. Existing private lists keep their original format until the owner enables sharing.

Shared operations are under `/api/grocery/lists/{id}/`. Use GET or POST `household/` to open or enable sharing, POST `members/` to invite by username, DELETE `members/{member_id}/` to revoke, POST `invitation/` to accept or decline, and GET `/api/grocery/lists/invitations/` for pending invites. POST `items/` adds a product. PATCH `items/{item_id}/` requires the current `revision` with the change. DELETE uses the `revision` query parameter. POST `optimize/` runs the existing optimizer against the current unpurchased list.

### Smart Pantry

Open **Smart Pantry** from the shopping navigation, or choose **Add to pantry** on an item in a confirmed receipt. Imports are explicit and a receipt line can be added once while its pantry entry exists. Receipt edits and financial reconciliation do not change pantry stock. Deleting a receipt disconnects its source reference and keeps the separately saved inventory entry.

Receipt quantities are estimates until checked. A quantity may be unknown. Record expiration dates manually and set a low-stock level per item to receive a replenishment suggestion when its quantity reaches that level. Date labels do not indicate food safety. Use **Add to shopping list** to enter the quantity to buy and send it to the existing browser shopping draft. From there you can optimize, save, or explicitly share the list.

Deal lookup requires per-item opt-in and checks current public EUR catalog offers. Recipe ideas are optional and generated locally from a short list of combinations and positive, user-confirmed quantities. They do not verify ingredient amounts, freshness, or dietary suitability. Pantry records and receipt references stay private.

Authenticated endpoints are GET/POST `/api/pantry/`, GET/PATCH/DELETE `/api/pantry/{id}/`, POST `/api/pantry/from-receipt/` with `receipt_item`, GET `/api/pantry/{id}/deals/`, and GET `/api/pantry/recipes/`.

# Smart Receipt Scanner API

The backend container includes local Tesseract with Bulgarian and English language data. For a Debian or Ubuntu installation outside Docker, install `tesseract-ocr`, `tesseract-ocr-bul`, and `tesseract-ocr-eng` and run Django migrations. The scanner returns HTTP 503 if local OCR is unavailable.

All endpoints require FinDash authentication.

| Method and path | Request and result |
| --- | --- |
| `POST /api/receipts/preview/` | Multipart `file` (JPEG, PNG, WebP or HEIC/HEIF on supported platforms). Repeat the field in reading order for up to three images of the same receipt, with a combined limit of 8 MiB and up to 16 megapixels per image. Optional fields are `source` (camera, gallery or upload), `date_order` (DMY by default, or MDY) and `allow_ai` (literal `true` or `false`, defaults to `false`). Returns a proposed receipt and a one-hour account-bound token. An exact previously confirmed upload returns `duplicate_id` instead. |
| `POST /api/receipts/confirm/` | JSON combining the preview token with reviewed receipt fields and items. Returns 201 for a new receipt or 200 with an existing receipt when the image or purchase fingerprint matches. |
| `GET /api/receipts/` | Paginated confirmed receipts belonging to the signed-in user. |
| `GET /api/receipts/{id}/` | Confirmed receipt and items. |
| `DELETE /api/receipts/{id}/` | Deletes the receipt and its items. The linked payment remains in the ledger. |
| `PATCH /api/receipts/{id}/reconciliation/` | Send `{"transaction": 123}` to link an existing owner-scoped payment or `{"transaction": null}` to unlink. |

Confirm with the merchant, purchase timestamp (prefer ISO 8601 with offset), original EUR or BGN currency, signed final total, and at least one reviewed item. Each item needs its original description and signed line total. A product ID optionally refers to an existing grocery catalog entry. Monetary inputs use decimal strings. Purchases use positive receipt totals and refunds use negative receipt totals. OCR suggestions depend on the layout and clarity of the image. Missing fields and suggested values require review.

Reconciliation requires matching currency and the opposite transaction sign, since the ledger represents expenses as negative amounts. A bank payment can link to one receipt. The user chooses the payment, and the link never creates or updates a transaction. Existing spending analytics continue to read the transaction ledger, so receipt line items simply provide item-level detail. The API reports if a link no longer matches after an edit to the transaction.

The preview uses null for missing values. If OCR reads only the date, `purchase_date` is returned and `purchased_at` remains null. `totals_check` reports whether the signed, extracted line totals add up to the printed total. A mismatch can reflect omitted rows, receipt-wide discounts, tax, or OCR errors. `possible_duplicate_ids` contains up to five receipts with the same merchant, amount, currency and date. These are suggestions for review.

Images and OCR text are processed in memory and discarded after the request. With explicit `allow_ai=true`, FinDash can send filtered OCR lines to Gemini to identify the merchant and pair split item descriptions with printed prices. Image pixels are never sent. Suggestions are checked against the OCR lines, and provider failures fall back to local results with an `ai_status` of `unavailable`. The API key stays on the server. Confirmed structured data and duplicate-detection hashes are retained until receipt deletion. Keep request bodies out of proxy and application logs and serve this API over HTTPS.

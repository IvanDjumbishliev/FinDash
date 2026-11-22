# Smart Receipt Scanner API

The backend container includes local Tesseract with Bulgarian and English language data. For a Debian or Ubuntu installation outside Docker, install `tesseract-ocr`, `tesseract-ocr-bul`, and `tesseract-ocr-eng` and run Django migrations. The scanner returns HTTP 503 if local OCR is unavailable.

All endpoints require FinDash authentication.

| Method and path | Request and result |
| --- | --- |
| `POST /api/receipts/preview/` | Multipart `file` (JPEG, PNG or WebP, up to 8 MiB), optional `source` (camera, gallery or upload), and optional `date_order` (DMY by default, or MDY). Returns a proposed receipt, review warnings and a one-hour account-bound token. An exact previously confirmed upload returns `duplicate_id` instead. |
| `POST /api/receipts/confirm/` | JSON combining the preview token with reviewed receipt fields and items. Returns 201 for a new receipt or 200 with an existing receipt when the image or purchase fingerprint matches. |
| `GET /api/receipts/` | Paginated confirmed receipts belonging to the signed-in user. |
| `GET /api/receipts/{id}/` | Confirmed receipt and items. |
| `DELETE /api/receipts/{id}/` | Deletes the receipt and its items. The linked payment remains in the ledger. |
| `PATCH /api/receipts/{id}/reconciliation/` | Send `{"transaction": 123}` to link an existing owner-scoped payment or `{"transaction": null}` to unlink. |

Confirm with the merchant, purchase timestamp (prefer ISO 8601 with offset), original EUR or BGN currency, signed final total, and at least one reviewed item. Each item needs its original description and signed line total. A product ID optionally refers to an existing grocery catalog entry. Monetary inputs use decimal strings. Purchases use positive receipt totals and refunds use negative receipt totals. OCR suggestions depend on the layout and clarity of the image. Missing fields and suggested values require review.

Reconciliation requires matching currency and the opposite transaction sign, since the ledger represents expenses as negative amounts. A bank payment can link to one receipt. The user chooses the payment, and the link never creates or updates a transaction. Existing spending analytics continue to read the transaction ledger, so receipt line items simply provide item-level detail. The API reports if a link no longer matches after an edit to the transaction.

Images and OCR text are processed locally in memory and discarded after the request. No image or raw OCR transcript is saved or sent to Gemini. Only the confirmed structured data and duplicate-detection hashes are retained until receipt deletion. Keep request bodies out of proxy and application logs and serve this API over HTTPS.

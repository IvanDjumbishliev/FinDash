# Loyalty Card Wallet

Open **More → Loyalty Wallet** or visit `/loyalty-wallet`. Add the retailer and the exact membership identifier printed or encoded on the loyalty card. Optional labels distinguish cards from the same retailer. Search runs in the browser against retailers and labels. Favorites come first, and the Favorites only filter keeps them easy to reach.

Choose **Identifier only** if you do not know the format or exact encoded value. Code 128, EAN-13, EAN-8, UPC-A, and QR are available after confirming the original format and value. EAN and UPC require the original check digit. The browser generates codes locally. Loyalty programs that use rotating tokens or codes containing URLs are outside this feature. Use their original app or card at checkout.

Images accept JPEG, PNG, WebP and supported HEIC/HEIF up to 8 MB. Upload images of loyalty cards only. FinDash validates and re-encodes each image to PNG without metadata. Images are served through authenticated private endpoints and removed when the card is deleted. The wallet supports up to 100 cards and 32 MiB of stored images per account.

| Authenticated endpoint | Behavior |
| --- | --- |
| `GET /api/loyalty-cards/` | Card summaries for the owner, with favorites first. The identifier is omitted. |
| `POST /api/loyalty-cards/` | Create a card. A code format requires `original_format_confirmed: true`. |
| `GET/PATCH/DELETE /api/loyalty-cards/{id}/` | Open, edit or delete a card. GET returns the identifier. Editing the format or encoded identifier requires reconfirmation when a code is enabled. |
| `GET/POST/DELETE /api/loyalty-cards/{id}/image/` | Read, upload or remove the private PNG. Upload multipart `file` and `loyalty_only=true`. |

Use membership identifiers only. The API rejects credential fields, URL-shaped values, and payment-number patterns that pass Luhn validation. The wallet stores data in the same private database as other account records. Keep that database and backups access-controlled and keep request bodies out of application and proxy logs.

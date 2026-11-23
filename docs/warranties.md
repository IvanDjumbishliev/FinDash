# Warranty Vault

Open **More → Warranty Vault**, or choose **Track warranty** under an item in Receipt history. For either workflow, enter the documented duration in months or the documented expiration date. FinDash copies purchase details from a confirmed receipt when asked and labels their source. Warranty terms always come from user input. Calendar-month durations clamp to the last valid day of the destination month. Expiry day is still active.

Set up to four reminder offsets from 0 to 365 days before expiry. A blank list turns reminders off. Celery checks hourly and sends in-app reminders through the existing notification center. The Warranty expiration category in Notification settings can suppress them.

| Authenticated endpoint | Behavior |
| --- | --- |
| `GET /api/warranties/` | Paginated list. Supports `q` for product or retailer and `status=active` or `expired`. |
| `POST /api/warranties/` | Add manually, or send `receipt_item` to copy purchase details from a confirmed receipt item you own. Use `duration_months` or `expires_on` to specify the documented term. |
| `GET/PATCH/DELETE /api/warranties/{id}/` | View, correct or delete a warranty. Deleting it removes its proof and associated reminder messages. Receipt edits preserve the link when they retain the item ID. Removing the receipt or item leaves the warranty's saved purchase details available. |
| `POST /api/warranties/{id}/proof/` | Upload or replace one proof image using multipart `file`. |
| `GET/DELETE /api/warranties/{id}/proof/` | Download or permanently remove the private attachment. |

Proofs accept JPEG, PNG, WebP and supported HEIC/HEIF images up to 8 MB. FinDash validates the image, corrects orientation, and stores a normalized grayscale PNG in the private database. The original file and its metadata are discarded. Proofs are available through the authenticated download endpoint. FinDash never publishes a media URL or sends proof images to OCR or external AI services. The vault allows up to 200 warranties and 64 MiB of proof images per account. Restrict database and backup access and apply the deployment's encryption and backup retention controls to those stores.

The daily Celery cleanup uses `WARRANTY_PROOF_RETENTION_DAYS` (365 by default) and `WARRANTY_RECORD_RETENTION_DAYS` (0 by default) after expiration. Use 0 to keep that data until explicit deletion, or account deletion. Automatic deletion from the live database does not change backup retention.

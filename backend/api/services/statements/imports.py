from datetime import datetime, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from api.models import StatementImport, Transaction
from api.services.notification_events import statement_imported
from api.services.notifications import after_commit

from .intelligence import assign_category, category_rules, flag_duplicates, merchant_identity, prepare_rows
from .normalization import StatementError

PREVIEW_LIFETIME = timedelta(minutes=30)


def expire_previews(owner=None):
    now = timezone.now()
    previews = StatementImport.objects.filter(
        status__in=[StatementImport.Status.READY, StatementImport.Status.NEEDS_MAPPING],
        expires_at__lte=now,
    )
    if owner is not None:
        previews = previews.filter(owner=owner)
    return previews.update(status=StatementImport.Status.EXPIRED, parsed_rows=[], updated_at=now)


def preview_rows(record):
    rows = record.parsed_rows
    if rows and "row_id" not in rows[0]:
        existing = [
            {**row, "category_supplied": row.get("category_supplied", row["category"] != Transaction.Category.GENERAL)}
            for row in rows
        ]
        return prepare_rows(record.owner, existing)[0]
    return [row.copy() for row in rows]


def claim_preview(record, revision):
    changed = StatementImport.objects.filter(
        pk=record.pk, owner_id=record.owner_id, status=StatementImport.Status.READY,
        expires_at__gt=timezone.now(), revision=revision,
    ).update(revision=revision + 1, updated_at=timezone.now())
    return bool(changed)


def review_import(record, revision, changes):
    if record.status != StatementImport.Status.READY or record.revision != revision:
        raise StatementError("The preview changed or expired. Reload it before reviewing.", status=409)

    rows = preview_rows(record)
    by_id = {row["row_id"]: row for row in rows}
    rules = category_rules(record.owner)
    for change in changes:
        row = by_id.get(change["row_id"])
        if row is None:
            raise StatementError("A selected row is not part of this preview.")
        if "merchant" in change:
            merchant, normalized = merchant_identity(change["merchant"])
            if not normalized:
                raise StatementError("Enter a merchant name with at least one letter.")
            row.update(merchant=merchant, normalized_merchant=normalized)
            if row["category_source"] != "manual" and "category" not in change:
                assign_category(row, rules)
        if "category" in change:
            row.update(category=change["category"], category_source="manual", category_confidence=1.0)
        if change.get("decision") in {"rejected", "pending"}:
            row["decision"] = change["decision"]
        elif change.get("decision") == "approved" and row["decision"] == "rejected":
            # Include previously rejected rows in the duplicate pass if they are being reinstated.
            row["decision"] = "pending"

    shown = {row["row_id"]: row.get("duplicate_matches") for row in rows}
    flag_duplicates(record.owner, rows)
    for change in changes:
        row = by_id[change["row_id"]]
        if change.get("decision") == "approved":
            flags = row["duplicate_matches"]
            if any(flags.values()) and (not change.get("allow_duplicate") or shown[row["row_id"]] != flags):
                raise StatementError("Review flagged duplicates before approving them.", status=409)
            row["decision"] = "approved"

    changed = StatementImport.objects.filter(
        pk=record.pk, owner_id=record.owner_id, status=StatementImport.Status.READY,
        expires_at__gt=timezone.now(), revision=revision,
    ).update(parsed_rows=rows, revision=revision + 1, updated_at=timezone.now())
    if not changed:
        raise StatementError("The preview changed or expired. Reload it before reviewing.", status=409)
    record.refresh_from_db()
    return record


def confirm_import(record, revision=None):
    if record.status == StatementImport.Status.IMPORTED:
        return record
    revision = record.revision if revision is None else revision

    with transaction.atomic():
        # Serialize confirmation of separate previews belonging to the same owner
        # on databases with row locking. The preview update is also a write on SQLite.
        get_user_model().objects.select_for_update().get(pk=record.owner_id)
        if not claim_preview(record, revision):
            record.refresh_from_db()
            if record.status == StatementImport.Status.IMPORTED:
                return record
            raise StatementError("The preview changed or expired. Reload it before confirming.", status=409)
        record.refresh_from_db()
        rows = preview_rows(record)
        prior_approvals = {row["row_id"] for row in rows if row["decision"] == "approved"}
        flag_duplicates(record.owner, rows)
        approved = [row for row in rows if row["decision"] == "approved"]
        if prior_approvals != {row["row_id"] for row in approved}:
            # Persist new duplicate flags so the user can explicitly review them.
            StatementImport.objects.filter(pk=record.pk).update(parsed_rows=rows)
            record.refresh_from_db()
            return record
        if not approved:
            raise StatementError("Approve at least one transaction before confirming.", status=409)

        Transaction.objects.bulk_create([
            Transaction(
                user_id=record.owner_id, amount=Decimal(row["amount"]),
                timestamp=datetime.fromisoformat(row["timestamp"]),
                particulars=row["particulars"], currency=row["currency"], category=row["category"],
                merchant=row["merchant"], normalized_merchant=row["normalized_merchant"],
                source_normalized_merchant=row.get("source_normalized_merchant", ""),
                statement_reference=row["reference"], statement_import=record,
            )
            for row in approved
        ], batch_size=250)
        StatementImport.objects.filter(pk=record.pk).update(
            status=StatementImport.Status.IMPORTED, parsed_rows=[], imported_count=len(approved),
            updated_at=timezone.now(),
        )
        after_commit(statement_imported, record.owner_id, record.pk)
    record.refresh_from_db()
    return record

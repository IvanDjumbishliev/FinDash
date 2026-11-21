from datetime import datetime, timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from api.models import StatementImport, Transaction

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


def confirm_import(record):
    if record.status == StatementImport.Status.IMPORTED:
        return record
    if record.status != StatementImport.Status.READY:
        raise StatementError("This import is no longer ready for confirmation.", status=409)
    now = timezone.now()
    rows = record.parsed_rows
    with transaction.atomic():
        claimed = StatementImport.objects.filter(
            pk=record.pk, owner=record.owner, status=StatementImport.Status.READY, expires_at__gt=now,
        ).update(status=StatementImport.Status.IMPORTED, parsed_rows=[], updated_at=now)
        if not claimed:
            record.refresh_from_db()
            if record.status == StatementImport.Status.IMPORTED:
                return record
            raise StatementError("This import is no longer ready for confirmation.", status=409)
        Transaction.objects.bulk_create([
            Transaction(
                user_id=record.owner_id,
                amount=Decimal(row["amount"]),
                timestamp=datetime.fromisoformat(row["timestamp"]),
                particulars=row["particulars"], currency=row["currency"], category=row["category"],
            )
            for row in rows
        ], batch_size=250)
    record.refresh_from_db()
    return record

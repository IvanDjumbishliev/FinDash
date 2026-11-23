"""Calendar expiry, private reminder events and proof retention."""
from calendar import monthrange
from datetime import date, timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from api.models import Notification, NotificationCategory, Warranty, WarrantyProof
from api.services.copilot_tools import account_timezone
from api.services.notifications import categories_for, notify

MAX_RECORDS = 200
MAX_PROOF_STORAGE = 64 * 1024 * 1024


def warranty_today(owner):
    return timezone.localdate(timezone=account_timezone(owner))


def expiry_from_months(purchase, months):
    year, zero_month = divmod(purchase.year * 12 + purchase.month - 1 + months, 12)
    month = zero_month + 1
    return date(year, month, min(purchase.day, monthrange(year, month)[1]))


@transaction.atomic
def warranty_reminders(owner, *, today=None):
    today = today or warranty_today(owner)
    category = NotificationCategory.WARRANTY_EXPIRATION
    if not categories_for(owner.pk)[category]:
        return 0
    warranties = Warranty.objects.select_for_update().filter(
        owner=owner, expires_on__range=(today, today + timedelta(days=365)),
    ).exclude(reminder_days=[])
    count = 0
    for warranty in warranties:
        days_left = (warranty.expires_on - today).days
        thresholds = [value for value in warranty.reminder_days if value >= days_left]
        if not thresholds:
            continue
        # Catch up to the nearest threshold after downtime, without a burst of older reminders.
        threshold = min(thresholds)
        event = f"warranty:{warranty.pk}:{warranty.expires_on.isoformat()}:{threshold}"
        if notify(owner.pk, category, event, payload={
            "warranty_id": warranty.pk, "product": warranty.product_name, "expires_on": warranty.expires_on.isoformat(),
        }):
            count += 1
    return count


@transaction.atomic
def delete_warranties(rows):
    ids = list(rows.select_for_update().values_list("pk", flat=True))
    if not ids:
        return 0
    Notification.objects.filter(
        category=NotificationCategory.WARRANTY_EXPIRATION, payload__warranty_id__in=ids,
    ).delete()
    count, _ = rows.filter(pk__in=ids).delete()
    return count


def purge_warranty_data(*, today=None):
    today = today or timezone.localdate()
    count = 0
    for rows, field, days in (
        (WarrantyProof.objects.all(), "warranty__expires_on", settings.WARRANTY_PROOF_RETENTION_DAYS),
        (Warranty.objects.all(), "expires_on", settings.WARRANTY_RECORD_RETENTION_DAYS),
    ):
        if not days:
            continue
        expired = rows.filter(**{f"{field}__lt": today - timedelta(days=days)})
        ids = list(expired.order_by("pk").values_list("pk", flat=True)[:1000])
        if ids:
            matching = expired.filter(pk__in=ids)
            if rows.model is Warranty:
                count += delete_warranties(matching)
            else:
                removed, _ = matching.delete()
                count += removed
    return count

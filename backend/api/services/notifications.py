import hashlib
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from api.models import (
    Notification, NotificationCategory, NotificationEvent, NotificationPreference, default_notification_categories,
)

MESSAGES = {
    NotificationCategory.BUDGET_THRESHOLD: ("Budget threshold reached", "Review your budget progress in FinDash."),
    NotificationCategory.SUBSCRIPTION_RENEWAL: ("Subscription renewal approaching", "Review upcoming renewals in FinDash."),
    NotificationCategory.UNUSUAL_SPENDING: ("Unusual spending detected", "Review a payment that differs from recent spending patterns."),
    NotificationCategory.STATEMENT_IMPORT: ("Statement import completed", "Your statement transactions are ready to review in FinDash."),
    NotificationCategory.FINANCIAL_REPORT: ("Financial report generated", "A financial report was generated in FinDash."),
    NotificationCategory.STOCK_THRESHOLD: ("Watchlist price threshold reached", "Check your price alerts in FinDash."),
}


def categories_for(owner_id):
    configured = NotificationPreference.objects.filter(owner_id=owner_id).values_list("categories", flat=True).first()
    return {**default_notification_categories(), **(configured or {})}


@transaction.atomic
def notify(owner_id, category, event_key):
    """Record an in-app event once. Delivery is outside this service."""
    if category not in NotificationCategory.values:
        raise ValueError("Unknown notification category.")
    if not categories_for(owner_id)[category]:
        return None
    digest = hashlib.sha256(str(event_key).encode()).hexdigest()
    event, created = NotificationEvent.objects.get_or_create(owner_id=owner_id, category=category, digest=digest)
    if not created:
        return None
    return Notification.objects.create(owner_id=owner_id, category=category, event=event)


def after_commit(callback, *args):
    transaction.on_commit(lambda: callback(*args), robust=True)


def retention_cutoff(now=None):
    return (now or timezone.now()) - timedelta(days=settings.NOTIFICATION_RETENTION_DAYS)


def purge_notifications(*, owner_id=None, now=None):
    rows = Notification.objects.filter(created_at__lt=retention_cutoff(now))
    if owner_id is not None:
        rows = rows.filter(owner_id=owner_id)
    count, _ = rows.delete()
    return count

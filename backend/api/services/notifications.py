import hashlib
import logging
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from api.models import (
    Notification, NotificationCategory, NotificationEvent, NotificationPreference, default_notification_categories,
)

logger = logging.getLogger(__name__)

MESSAGES = {
    NotificationCategory.BUDGET_THRESHOLD: ("Budget threshold reached", "Review your budget progress in FinDash."),
    NotificationCategory.SUBSCRIPTION_RENEWAL: ("Subscription renewal approaching", "Review upcoming renewals in FinDash."),
    NotificationCategory.UNUSUAL_SPENDING: ("Unusual spending detected", "Review a payment that differs from recent spending patterns."),
    NotificationCategory.STATEMENT_IMPORT: ("Statement import completed", "Your statement transactions are ready to review in FinDash."),
    NotificationCategory.FINANCIAL_REPORT: ("Financial report generated", "A financial report was generated in FinDash."),
    NotificationCategory.WARRANTY_EXPIRATION: ("Warranty expiring", "Review the expiration date in Warranty Vault."),
    NotificationCategory.GROCERY_DEAL: ("Matching grocery offer", "Review the advertised offer in My Products."),
    NotificationCategory.STOCK_THRESHOLD: ("Watchlist price threshold reached", "Check your price alerts in FinDash."),
}


def categories_for(owner_id):
    configured = NotificationPreference.objects.filter(owner_id=owner_id).values_list("categories", flat=True).first()
    return {**default_notification_categories(), **(configured or {})}


def reserve_event(owner_id, category, event_key):
    digest = hashlib.sha256(str(event_key).encode()).hexdigest()
    return NotificationEvent.objects.get_or_create(owner_id=owner_id, category=category, digest=digest)


@transaction.atomic
def notify(owner_id, category, event_key, *, payload=None):
    """Record an in-app event once. Delivery is outside this service."""
    if category not in NotificationCategory.values:
        raise ValueError("Unknown notification category.")
    if not categories_for(owner_id)[category]:
        return None
    event, created = reserve_event(owner_id, category, event_key)
    if not created:
        return None
    return Notification.objects.create(owner_id=owner_id, category=category, event=event, payload=payload or {})


def after_commit(callback, *args):
    def run():
        try:
            callback(*args)
        except Exception:
            logger.warning("Post-commit notification processing failed")

    transaction.on_commit(run)


def retention_cutoff(now=None):
    return (now or timezone.now()) - timedelta(days=settings.NOTIFICATION_RETENTION_DAYS)


def purge_notifications(*, owner_id=None, now=None):
    rows = Notification.objects.filter(created_at__lt=retention_cutoff(now))
    if owner_id is not None:
        rows = rows.filter(owner_id=owner_id)
    count, _ = rows.delete()
    return count

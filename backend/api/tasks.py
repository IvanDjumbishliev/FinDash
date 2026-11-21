import json
import logging

from billiard.exceptions import SoftTimeLimitExceeded
from celery import Task, shared_task
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import InterfaceError, OperationalError
from django.utils import timezone
from kombu.exceptions import OperationalError as BrokerUnavailable

from api.services.notification_events import (
    MarketQuotesUnavailable,
    check_budgets,
    generate_renewal_alerts,
    generate_stock_alerts,
)
from api.services.notifications import purge_notifications

logger = logging.getLogger(__name__)
BATCH_SIZE = 200


class NotificationTaskFailure(Exception):
    pass


class NotificationTask(Task):
    acks_late = True
    max_retries = 3

    def __call__(self, *args, **kwargs):
        try:
            count = super().__call__(*args, **kwargs)
        except (OperationalError, InterfaceError, BrokerUnavailable, MarketQuotesUnavailable, SoftTimeLimitExceeded):
            attempt = self.request.retries
            if attempt >= self.max_retries:
                self.log_outcome(logging.ERROR, "retry_exhausted")
                raise NotificationTaskFailure("Notification task retries exhausted.") from None
            delay = min(60 * 2**attempt, 300)
            self.log_outcome(logging.WARNING, "retry_scheduled", delay_seconds=delay)
            raise self.retry(
                exc=NotificationTaskFailure("Notification task temporarily unavailable."),
                countdown=delay,
                argsrepr="(<redacted>)",
                kwargsrepr="{}",
            ) from None
        self.log_outcome(logging.INFO, "completed", count=count)
        return count

    def log_outcome(self, level, outcome, **fields):
        logger.log(level, "%s", json.dumps({
            "event": "notification_task",
            "task": self.name,
            "outcome": outcome,
            "retry": self.request.retries,
            **fields,
        }))


def enqueue(task, *args):
    # Celery event metadata and task failure logs omit account identifiers.
    task.apply_async(args=args, argsrepr="(<redacted>)", kwargsrepr="{}", retry=False)


def fan_out(owners, task, scheduler, cursor):
    owner_ids = list(
        owners.filter(is_active=True, pk__gt=cursor).order_by("pk")
        .values_list("pk", flat=True).distinct()[:BATCH_SIZE]
    )
    for owner_id in owner_ids:
        enqueue(task, owner_id)
    if len(owner_ids) == BATCH_SIZE:
        enqueue(scheduler, owner_ids[-1])
    return len(owner_ids)


@shared_task(base=NotificationTask, name="notifications.schedule_renewals")
def schedule_renewals(cursor=0):
    owners = get_user_model().objects.filter(subscription_preferences__renewal_reminders=True)
    return fan_out(owners, check_owner_renewals, schedule_renewals, cursor)


@shared_task(base=NotificationTask, name="notifications.schedule_budgets")
def schedule_budgets(cursor=0):
    period = timezone.localdate().replace(day=1)
    owners = get_user_model().objects.filter(budgets__period=period, budgets__archived=False)
    return fan_out(owners, check_owner_budgets, schedule_budgets, cursor)


@shared_task(base=NotificationTask, name="notifications.schedule_market")
def schedule_market(cursor=0):
    if not settings.NOTIFICATION_MARKET_CHECKS_ENABLED:
        return 0
    owners = get_user_model().objects.filter(notification_stock_alerts__isnull=False)
    return fan_out(owners, check_owner_market, schedule_market, cursor)


def active_owner(owner_id):
    return get_user_model().objects.filter(pk=owner_id, is_active=True).first()


@shared_task(base=NotificationTask, name="notifications.check_renewals")
def check_owner_renewals(owner_id):
    owner = active_owner(owner_id)
    return generate_renewal_alerts(owner) if owner else 0


@shared_task(base=NotificationTask, name="notifications.check_budgets")
def check_owner_budgets(owner_id):
    owner = active_owner(owner_id)
    return check_budgets(owner.pk, {timezone.localdate().replace(day=1)}) if owner else 0


@shared_task(base=NotificationTask, name="notifications.check_market")
def check_owner_market(owner_id):
    owner = active_owner(owner_id) if settings.NOTIFICATION_MARKET_CHECKS_ENABLED else None
    return generate_stock_alerts(owner, retry_unavailable=True) if owner else 0


@shared_task(base=NotificationTask, name="notifications.purge")
def purge():
    return purge_notifications()

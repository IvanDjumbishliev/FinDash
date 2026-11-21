from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db.models import Q

from api.services.notification_events import generate_renewal_alerts, generate_stock_alerts
from api.services.notifications import purge_notifications


class Command(BaseCommand):
    help = "Generate due in-app notifications and remove notifications beyond retention."

    def add_arguments(self, parser):
        parser.add_argument("--owner-id", type=int)

    def handle(self, *args, **options):
        owner_id = options["owner_id"]
        owners = get_user_model().objects.filter(is_active=True).filter(
            Q(subscription_preferences__renewal_reminders=True) | Q(notification_stock_alerts__isnull=False),
        ).distinct()
        if owner_id is not None:
            owners = owners.filter(pk=owner_id)
        renewals = stocks = 0
        for owner in owners.iterator():
            renewals += generate_renewal_alerts(owner)
            stocks += generate_stock_alerts(owner)
        purged = purge_notifications(owner_id=owner_id)
        self.stdout.write(f"Created {renewals} renewal and {stocks} stock notifications. Purged {purged} expired inbox entries.")

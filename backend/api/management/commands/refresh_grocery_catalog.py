from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from api.models import GroceryRetailer
from api.services.grocery_catalog import refresh_catalog


class Command(BaseCommand):
    help = "Normalize offers through an authorized retailer integration."

    def add_arguments(self, parser):
        parser.add_argument("retailer", choices=GroceryRetailer.values, nargs="+")

    def handle(self, *args, **options):
        retailers = dict.fromkeys(options["retailer"])
        disabled = retailers.keys() - settings.GROCERY_CATALOG_RETAILERS
        if disabled:
            raise CommandError(f"Catalog refresh is disabled for {', '.join(sorted(disabled))}.")
        for retailer in retailers:
            status, count = refresh_catalog(retailer)
            self.stdout.write(f"{retailer} {status} ({count} offers in the last successful refresh)")

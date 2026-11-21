from django.core.management.base import BaseCommand

from api.services.statements.imports import expire_previews


class Command(BaseCommand):
    help = "Clear transaction rows from expired bank statement previews."

    def handle(self, *args, **options):
        self.stdout.write(f"Expired {expire_previews()} statement previews.")

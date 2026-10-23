from django.core.management.base import BaseCommand

from booking.operations.services.rental_channels import dispatch_queued_first_party_events


class Command(BaseCommand):
    help = "Dispatch queued first-party portal channel events when endpoints are configured."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=100)
        parser.add_argument("--execute", action="store_true", help="Send events to configured portal endpoints.")

    def handle(self, *args, **options):
        result = dispatch_queued_first_party_events(limit=max(1, options["limit"]), execute=options["execute"])
        mode = "dispatched" if options["execute"] else "previewed"
        self.stdout.write(self.style.SUCCESS(f"First-party events {mode}: {result}"))

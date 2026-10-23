from django.core.management.base import BaseCommand

from booking.operations.models import EInvoiceTransmission, RentalInvoice
from booking.operations.services.e_invoice import queue_invoice_export


class Command(BaseCommand):
    help = "Queue issued rental invoices for a provider-neutral e-invoice/accounting export."

    def add_arguments(self, parser):
        parser.add_argument("--provider", default="manual")
        parser.add_argument("--execute", action="store_true", help="Create or refresh export queue records.")

    def handle(self, *args, **options):
        invoices = RentalInvoice.objects.select_related("invoice").filter(invoice__status="issued")
        total = invoices.count()
        if not options["execute"]:
            self.stdout.write(self.style.WARNING(f"{total} issued rental invoices found; use --execute to queue."))
            return
        queued = 0
        for rental_invoice in invoices.iterator():
            queue_invoice_export(invoice=rental_invoice.invoice, provider=options["provider"])
            queued += 1
        self.stdout.write(self.style.SUCCESS(f"{queued} rental invoices queued for export."))

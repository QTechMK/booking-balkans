from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand
from django.utils import timezone
import requests

from booking.operations.models import RentalNotification


class Command(BaseCommand):
    help = "Dispatch queued vehicle-rental email and WhatsApp notifications."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=100)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        rows = RentalNotification.objects.select_related("booking", "booking__property").filter(
            status="pending"
        ).order_by("created_at")[: options["limit"]]
        sent = failed = deferred = 0
        for row in rows:
            if options["dry_run"]:
                self.stdout.write(f"would send {row.channel} notification to {row.recipient}")
                continue
            try:
                provider_reference = self._send(row)
            except RuntimeError as exc:
                if str(exc) == "provider_not_configured":
                    deferred += 1
                    continue
                row.status = "failed"
                row.error_message = str(exc)[:4000]
                row.save(update_fields=["status", "error_message"])
                failed += 1
                continue
            row.status = "sent"
            row.sent_at = timezone.now()
            row.error_message = provider_reference
            row.save(update_fields=["status", "sent_at", "error_message"])
            sent += 1
        self.stdout.write(self.style.SUCCESS(f"Rental notification dispatch: {sent} sent, {failed} failed, {deferred} deferred."))

    @staticmethod
    def _send(row):
        booking = row.booking
        body = f"Kiralama talebiniz alındı. Rezervasyon kodu: {booking.confirmation_code}"
        if row.channel == "email":
            try:
                send_mail("Araç kiralama talebi", body, None, [row.recipient], fail_silently=False)
            except Exception as exc:
                raise RuntimeError(f"email provider error: {exc}") from exc
            return ""
        webhook = getattr(settings, "MARKETING_WHATSAPP_WEBHOOK_URL", "")
        token = getattr(settings, "MARKETING_WHATSAPP_WEBHOOK_TOKEN", "")
        if not webhook:
            raise RuntimeError("provider_not_configured")
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            response = requests.post(webhook, headers=headers, json={"to": row.recipient, "body": body, "booking_id": booking.id}, timeout=15)
        except requests.RequestException as exc:
            raise RuntimeError(f"provider connection error: {exc}") from exc
        if not response.ok:
            raise RuntimeError(f"provider returned HTTP {response.status_code}")
        return ""

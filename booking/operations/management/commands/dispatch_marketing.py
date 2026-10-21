from django.conf import settings
from django.core.management.base import BaseCommand
from django.core.mail import send_mail
from django.utils import timezone
import requests

from booking.operations.models import MarketingCampaign, MarketingDelivery, MessageTemplate


class Command(BaseCommand):
    help = "Dispatch queued CRM campaign deliveries through email or configured channel webhooks."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=100)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        now = timezone.now()
        deliveries = MarketingDelivery.objects.select_related("campaign", "campaign__property", "campaign__template", "guest").filter(
            status=MarketingDelivery.Status.QUEUED,
            campaign__status=MarketingCampaign.Status.SCHEDULED,
            campaign__template__is_active=True,
        ).filter(
            campaign__scheduled_at__isnull=True,
        ) | MarketingDelivery.objects.select_related("campaign", "campaign__property", "campaign__template", "guest").filter(
            status=MarketingDelivery.Status.QUEUED,
            campaign__status=MarketingCampaign.Status.SCHEDULED,
            campaign__template__is_active=True,
            campaign__scheduled_at__lte=now,
        )
        deliveries = deliveries.distinct().order_by("queued_at")[: options["limit"]]
        sent = failed = deferred = 0
        for delivery in deliveries:
            template = delivery.campaign.template
            if options["dry_run"]:
                self.stdout.write(f"would send {delivery.recipient} via {delivery.channel}")
                continue
            try:
                provider_id = self._dispatch(delivery, template)
            except RuntimeError as exc:
                if str(exc) == "provider_not_configured":
                    deferred += 1
                    continue
                delivery.status = MarketingDelivery.Status.FAILED
                delivery.error = str(exc)[:4000]
                delivery.save(update_fields=["status", "error"])
                failed += 1
                continue
            delivery.status = MarketingDelivery.Status.SENT
            delivery.provider_message_id = provider_id
            delivery.sent_at = now
            delivery.error = ""
            delivery.save(update_fields=["status", "provider_message_id", "sent_at", "error"])
            sent += 1
        self.stdout.write(self.style.SUCCESS(f"Marketing dispatch complete: {sent} sent, {failed} failed, {deferred} deferred."))

    @staticmethod
    def _dispatch(delivery, template):
        if delivery.channel == MessageTemplate.Channel.EMAIL:
            try:
                send_mail(template.subject or delivery.campaign.name, template.body, None, [delivery.recipient], fail_silently=False)
            except Exception as exc:
                raise RuntimeError(f"email provider error: {exc}") from exc
            return ""
        config = {
            MessageTemplate.Channel.SMS: (settings.MARKETING_SMS_WEBHOOK_URL, settings.MARKETING_SMS_WEBHOOK_TOKEN),
            MessageTemplate.Channel.WHATSAPP: (settings.MARKETING_WHATSAPP_WEBHOOK_URL, settings.MARKETING_WHATSAPP_WEBHOOK_TOKEN),
        }.get(delivery.channel)
        if not config or not config[0]:
            raise RuntimeError("provider_not_configured")
        headers = {"Content-Type": "application/json"}
        if config[1]:
            headers["Authorization"] = f"Bearer {config[1]}"
        try:
            response = requests.post(config[0], headers=headers, json={
                "channel": delivery.channel,
                "to": delivery.recipient,
                "body": template.body,
                "subject": template.subject,
                "campaign_id": delivery.campaign_id,
                "delivery_id": delivery.id,
            }, timeout=15)
        except requests.RequestException as exc:
            raise RuntimeError(f"provider connection error: {exc}") from exc
        if not response.ok:
            raise RuntimeError(f"provider returned HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        return str(payload.get("id") or payload.get("message_id") or "")

from django.core.management.base import BaseCommand
from django.core.mail import send_mail
from django.utils import timezone

from booking.operations.models import MarketingCampaign, MarketingDelivery, MessageTemplate


class Command(BaseCommand):
    help = "Dispatch queued email marketing deliveries; leave unsupported channels queued."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=100)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        now = timezone.now()
        deliveries = MarketingDelivery.objects.select_related("campaign", "campaign__property", "guest").filter(
            status=MarketingDelivery.Status.QUEUED,
            campaign__status=MarketingCampaign.Status.SCHEDULED,
            campaign__template__is_active=True,
            campaign__template__channel=MessageTemplate.Channel.EMAIL,
        ).filter(
            campaign__scheduled_at__isnull=True,
        ) | MarketingDelivery.objects.select_related("campaign", "campaign__property", "guest").filter(
            status=MarketingDelivery.Status.QUEUED,
            campaign__status=MarketingCampaign.Status.SCHEDULED,
            campaign__template__is_active=True,
            campaign__template__channel=MessageTemplate.Channel.EMAIL,
            campaign__scheduled_at__lte=now,
        )
        deliveries = deliveries.distinct().order_by("queued_at")[: options["limit"]]
        sent = failed = 0
        for delivery in deliveries:
            template = delivery.campaign.template
            if options["dry_run"]:
                self.stdout.write(f"would send {delivery.recipient} via email")
                continue
            try:
                send_mail(
                    template.subject or delivery.campaign.name,
                    template.body,
                    None,
                    [delivery.recipient],
                    fail_silently=False,
                )
            except Exception as exc:  # provider failures must remain visible in the queue
                delivery.status = MarketingDelivery.Status.FAILED
                delivery.error = str(exc)[:4000]
                delivery.save(update_fields=["status", "error"])
                failed += 1
                continue
            delivery.status = MarketingDelivery.Status.SENT
            delivery.sent_at = now
            delivery.error = ""
            delivery.save(update_fields=["status", "sent_at", "error"])
            sent += 1

        self.stdout.write(self.style.SUCCESS(f"Marketing dispatch complete: {sent} sent, {failed} failed."))

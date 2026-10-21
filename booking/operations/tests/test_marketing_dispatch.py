from datetime import timedelta

import pytest
from django.core import mail
from django.core.management import call_command
from django.utils import timezone

from booking.operations.models import MarketingCampaign, MarketingDelivery, MessageTemplate
from booking.reservations.models import Guest
from booking.tenancy.models import Organization, Property


@pytest.fixture
def email_campaign():
    organization = Organization.objects.create(name="Hotel Group", slug="hotel-group")
    property_ = Property.objects.create(organization=organization, name="Main Hotel", slug="main-hotel")
    guest = Guest.objects.create(property=property_, first_name="Ada", email="ada@example.com")
    template = MessageTemplate.objects.create(
        property=property_, code="welcome", name="Welcome", channel=MessageTemplate.Channel.EMAIL,
        subject="Welcome", body="Hello guest",
    )
    campaign = MarketingCampaign.objects.create(
        property=property_, name="Welcome campaign", template=template,
        status=MarketingCampaign.Status.SCHEDULED,
    )
    delivery = MarketingDelivery.objects.create(
        campaign=campaign, guest=guest, channel=MessageTemplate.Channel.EMAIL,
        recipient=guest.email,
    )
    return delivery


@pytest.mark.django_db
def test_dispatch_marketing_sends_queued_email(email_campaign, settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    call_command("dispatch_marketing")
    email_campaign.refresh_from_db()
    assert email_campaign.status == MarketingDelivery.Status.SENT
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["ada@example.com"]


@pytest.mark.django_db
def test_dispatch_marketing_skips_future_campaign(email_campaign):
    email_campaign.campaign.scheduled_at = timezone.now() + timedelta(hours=1)
    email_campaign.campaign.save(update_fields=["scheduled_at"])
    call_command("dispatch_marketing")
    email_campaign.refresh_from_db()
    assert email_campaign.status == MarketingDelivery.Status.QUEUED

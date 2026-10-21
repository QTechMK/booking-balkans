from datetime import date
from decimal import Decimal

import pytest

from booking.reservations.models import ReservationChannel, ReservationSource
from booking.tenancy.models import ChannelRateRule, ChannelRateRuleType
from booking.tenancy.models import PriceParityObservation, PriceParityStatus
from booking.tenancy.models import Organization, Property, RatePlan, UnitType
from booking.tenancy.services.pricing import calculate_channel_amount


@pytest.fixture
def pricing_setup():
    organization = Organization.objects.create(name="Balkans", slug="pricing-balkans")
    property_ = Property.objects.create(
        organization=organization,
        name="Pricing Hotel",
        slug="pricing-hotel",
    )
    unit_type = UnitType.objects.create(
        property=property_, name="Standard", code="standard-pricing"
    )
    rate_plan = RatePlan.objects.create(
        property=property_,
        unit_type=unit_type,
        name="Flexible",
        code="flexible-pricing",
    )
    channel = ReservationChannel.objects.create(
        property=property_,
        name="Direct site",
        code="direct-site",
        source=ReservationSource.DIRECT,
    )
    return property_, rate_plan, channel


@pytest.mark.django_db
def test_channel_rate_rule_applies_percentage_and_prefers_rate_specific(pricing_setup):
    property_, rate_plan, channel = pricing_setup
    ChannelRateRule.objects.create(
        property=property_,
        channel=channel,
        name="Generic discount",
        adjustment=Decimal("-5"),
    )
    ChannelRateRule.objects.create(
        property=property_,
        channel=channel,
        rate_plan=rate_plan,
        name="Flexible discount",
        adjustment=Decimal("-10"),
        priority=0,
    )

    assert calculate_channel_amount(
        amount=Decimal("1000"), channel=channel, rate_plan=rate_plan
    ) == Decimal("900.00")


@pytest.mark.django_db
def test_price_parity_fails_closed_when_terms_do_not_match(pricing_setup):
    property_, rate_plan, channel = pricing_setup
    observation = PriceParityObservation.objects.create(
        property=property_,
        rate_plan=rate_plan,
        channel=channel,
        competitor_name="Example OTA",
        check_in=date(2026, 11, 1),
        check_out=date(2026, 11, 3),
        direct_amount=Decimal("1900"),
        competitor_amount=Decimal("2000"),
        terms_match=False,
    )

    assert observation.status == PriceParityStatus.UNCOMPARABLE


@pytest.mark.django_db
def test_price_parity_classifies_comparable_prices(pricing_setup):
    property_, rate_plan, channel = pricing_setup
    observation = PriceParityObservation.objects.create(
        property=property_,
        rate_plan=rate_plan,
        channel=channel,
        competitor_name="Example OTA",
        check_in=date(2026, 11, 1),
        check_out=date(2026, 11, 3),
        direct_amount=Decimal("1900"),
        competitor_amount=Decimal("2000"),
        terms_match=True,
    )

    assert observation.status == PriceParityStatus.BELOW

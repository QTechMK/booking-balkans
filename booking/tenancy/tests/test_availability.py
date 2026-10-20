from datetime import date
from decimal import Decimal

import pytest

from booking.tenancy.models import DailyRate
from booking.tenancy.models import Inventory
from booking.tenancy.models import RatePlan
from booking.tenancy.models import RateRestriction
from booking.tenancy.models import Organization
from booking.tenancy.models import Property
from booking.tenancy.models import UnitType
from booking.tenancy.services.availability import get_availability


@pytest.fixture
def rate_setup():
    organization = Organization.objects.create(name="Balkans", slug="balkans")
    property_ = Property.objects.create(
        organization=organization,
        name="Main Hotel",
        slug="main-hotel",
    )
    unit_type = UnitType.objects.create(
        property=property_,
        name="Standard Room",
        code="standard-room",
        capacity_per_unit=2,
    )
    rate_plan = RatePlan.objects.create(
        property=property_,
        unit_type=unit_type,
        name="Flexible",
        code="flexible",
    )
    for day, amount in (
        (date(2026, 11, 1), "1500.00"),
        (date(2026, 11, 2), "1600.00"),
    ):
        Inventory.objects.create(
            property=property_,
            unit_type=unit_type,
            date=day,
            total_capacity=5,
            blocked_capacity=1,
        )
        DailyRate.objects.create(rate_plan=rate_plan, date=day, amount=amount)
    return property_, rate_plan


@pytest.mark.django_db
def test_availability_returns_daily_prices_and_sellable_capacity(rate_setup):
    property_, rate_plan = rate_setup

    result = get_availability(
        property_id=property_.id,
        rate_plan_id=rate_plan.id,
        check_in=date(2026, 11, 1),
        check_out=date(2026, 11, 3),
    )

    assert result.available is True
    assert result.nights == 2  # noqa: PLR2004
    assert result.total_amount == Decimal("3100.00")
    assert [day.capacity for day in result.days] == [4, 4]


@pytest.mark.django_db
def test_availability_rejects_missing_inventory_or_rate(rate_setup):
    property_, rate_plan = rate_setup

    missing_inventory = get_availability(
        property_id=property_.id,
        rate_plan_id=rate_plan.id,
        check_in=date(2026, 11, 1),
        check_out=date(2026, 11, 4),
    )
    assert missing_inventory.available is False
    assert missing_inventory.reason == "inventory_missing"

    Inventory.objects.create(
        property=property_,
        unit_type=rate_plan.unit_type,
        date=date(2026, 11, 3),
        total_capacity=5,
    )
    missing_rate = get_availability(
        property_id=property_.id,
        rate_plan_id=rate_plan.id,
        check_in=date(2026, 11, 2),
        check_out=date(2026, 11, 4),
    )
    assert missing_rate.available is False
    assert missing_rate.reason == "rate_missing"


@pytest.mark.django_db
def test_availability_applies_stop_sell_and_night_restrictions(rate_setup):
    property_, rate_plan = rate_setup
    RateRestriction.objects.create(
        rate_plan=rate_plan,
        date=date(2026, 11, 2),
        stop_sell=True,
    )
    result = get_availability(
        property_id=property_.id,
        rate_plan_id=rate_plan.id,
        check_in=date(2026, 11, 1),
        check_out=date(2026, 11, 3),
    )
    assert result.available is False
    assert result.reason == "stop_sell"


@pytest.mark.django_db
def test_availability_applies_close_arrival_and_departure(rate_setup):
    property_, rate_plan = rate_setup
    RateRestriction.objects.create(
        rate_plan=rate_plan,
        date=date(2026, 11, 1),
        close_to_arrival=True,
    )
    arrival_result = get_availability(
        property_id=property_.id,
        rate_plan_id=rate_plan.id,
        check_in=date(2026, 11, 1),
        check_out=date(2026, 11, 2),
    )
    assert arrival_result.reason == "close_to_arrival"

    RateRestriction.objects.filter(
        rate_plan=rate_plan,
        date=date(2026, 11, 1),
    ).update(close_to_arrival=False, close_to_departure=True)
    departure_result = get_availability(
        property_id=property_.id,
        rate_plan_id=rate_plan.id,
        check_in=date(2026, 11, 1),
        check_out=date(2026, 11, 2),
    )
    assert departure_result.reason == "close_to_departure"


@pytest.mark.django_db
def test_availability_does_not_cross_property_boundaries(rate_setup):
    property_, rate_plan = rate_setup
    other_organization = Organization.objects.create(name="Other", slug="other")
    other_property = Property.objects.create(
        organization=other_organization,
        name="Other Hotel",
        slug="other-hotel",
    )

    result = get_availability(
        property_id=other_property.id,
        rate_plan_id=rate_plan.id,
        check_in=date(2026, 11, 1),
        check_out=date(2026, 11, 2),
    )
    assert result.available is False
    assert result.reason == "rate_plan_unavailable"


def test_availability_rejects_invalid_date_range():
    with pytest.raises(ValueError, match="check_out must be after check_in"):
        get_availability(
            property_id=1,
            rate_plan_id=1,
            check_in=date(2026, 11, 2),
            check_out=date(2026, 11, 2),
        )

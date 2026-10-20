from datetime import date
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from booking.reservations.models import Guest
from booking.reservations.models import HoldStatus
from booking.reservations.models import Reservation
from booking.reservations.models import ReservationHold
from booking.reservations.models import ReservationItem
from booking.reservations.models import ReservationStatus
from booking.reservations.services.holds import HoldUnavailable
from booking.reservations.services.holds import create_hold
from booking.reservations.services.holds import expire_holds
from booking.tenancy.models import DailyRate
from booking.tenancy.models import Inventory
from booking.tenancy.models import Organization
from booking.tenancy.models import Property
from booking.tenancy.models import RatePlan
from booking.tenancy.models import UnitType


@pytest.fixture
def hold_setup():
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
    )
    rate_plan = RatePlan.objects.create(
        property=property_,
        unit_type=unit_type,
        name="Flexible",
        code="flexible",
    )
    for day in (date(2026, 11, 1), date(2026, 11, 2)):
        Inventory.objects.create(
            property=property_,
            unit_type=unit_type,
            date=day,
            total_capacity=5,
            blocked_capacity=1,
        )
        DailyRate.objects.create(
            rate_plan=rate_plan,
            date=day,
            amount=Decimal("1500.00"),
        )
    return property_, unit_type, rate_plan


@pytest.mark.django_db
def test_create_hold_reduces_availability_until_expiry(hold_setup):
    property_, unit_type, rate_plan = hold_setup
    hold, result = create_hold(
        property_id=property_.id,
        unit_type_id=unit_type.id,
        rate_plan_id=rate_plan.id,
        check_in=date(2026, 11, 1),
        check_out=date(2026, 11, 3),
        quantity=2,
        ttl_seconds=900,
    )

    assert hold.status == HoldStatus.ACTIVE
    assert result.available is True

    from booking.tenancy.services.availability import get_availability

    after_hold = get_availability(
        property_id=property_.id,
        rate_plan_id=rate_plan.id,
        check_in=date(2026, 11, 1),
        check_out=date(2026, 11, 3),
    )
    assert after_hold.days[0].capacity == 2  # noqa: PLR2004


@pytest.mark.django_db
def test_expired_hold_is_not_counted_and_can_be_marked_expired(hold_setup):
    property_, unit_type, rate_plan = hold_setup
    hold = ReservationHold.objects.create(
        property=property_,
        unit_type=unit_type,
        rate_plan=rate_plan,
        check_in=date(2026, 11, 1),
        check_out=date(2026, 11, 3),
        quantity=2,
        expires_at=timezone.now() - timedelta(minutes=1),
    )

    updated = expire_holds()
    hold.refresh_from_db()
    assert updated == 1
    assert hold.status == HoldStatus.EXPIRED


@pytest.mark.django_db
def test_confirmed_reservation_reduces_availability(hold_setup):
    property_, unit_type, rate_plan = hold_setup
    guest = Guest.objects.create(property=property_, first_name="Ada")
    reservation = Reservation.objects.create(
        property=property_,
        guest=guest,
        status=ReservationStatus.CONFIRMED,
        check_in=date(2026, 11, 1),
        check_out=date(2026, 11, 3),
    )
    ReservationItem.objects.create(
        reservation=reservation,
        unit_type=unit_type,
        rate_plan=rate_plan,
        quantity=2,
    )

    from booking.tenancy.services.availability import get_availability

    result = get_availability(
        property_id=property_.id,
        rate_plan_id=rate_plan.id,
        check_in=date(2026, 11, 1),
        check_out=date(2026, 11, 3),
    )
    assert result.days[0].capacity == 2  # noqa: PLR2004


@pytest.mark.django_db
def test_hold_rejects_insufficient_capacity(hold_setup):
    property_, unit_type, rate_plan = hold_setup

    with pytest.raises(HoldUnavailable) as error:
        create_hold(
            property_id=property_.id,
            unit_type_id=unit_type.id,
            rate_plan_id=rate_plan.id,
            check_in=date(2026, 11, 1),
            check_out=date(2026, 11, 3),
            quantity=5,
        )

    assert error.value.reason == "no_capacity"

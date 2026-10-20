from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from booking.reservations.models import Guest
from booking.reservations.models import Reservation
from booking.reservations.models import ReservationItem
from booking.reservations.models import ReservationSource
from booking.reservations.models import ReservationStatus
from booking.reservations.models import StayStatus
from booking.tenancy.models import Organization
from booking.tenancy.models import Property
from booking.tenancy.models import RatePlan
from booking.tenancy.models import Unit
from booking.tenancy.models import UnitType


@pytest.fixture
def reservation_setup():
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
    unit = Unit.objects.create(
        property=property_,
        unit_type=unit_type,
        code="101",
    )
    guest = Guest.objects.create(
        property=property_,
        first_name="Ada",
        last_name="Booking",
        email="ada@example.com",
    )
    return property_, unit_type, rate_plan, unit, guest


@pytest.mark.django_db
def test_reservation_and_item_keep_price_snapshot(reservation_setup):
    property_, unit_type, rate_plan, unit, guest = reservation_setup
    reservation = Reservation.objects.create(
        property=property_,
        guest=guest,
        status=ReservationStatus.CONFIRMED,
        source=ReservationSource.DIRECT,
        check_in=date(2026, 11, 1),
        check_out=date(2026, 11, 3),
        subtotal_amount=Decimal("3000.00"),
        tax_amount=Decimal("300.00"),
        total_amount=Decimal("3300.00"),
        price_snapshot={"rate_plan": "flexible", "nightly": [1500, 1500]},
    )
    item = ReservationItem.objects.create(
        reservation=reservation,
        unit_type=unit_type,
        rate_plan=rate_plan,
        unit=unit,
        quantity=1,
        nightly_amount=Decimal("1500.00"),
        total_amount=Decimal("3000.00"),
        price_snapshot={"currency": "TRY", "amount": "1500.00"},
    )

    assert reservation.reference
    assert reservation.items.get() == item
    assert reservation.price_snapshot["nightly"] == [1500, 1500]
    assert item.price_snapshot["amount"] == "1500.00"


@pytest.mark.django_db
def test_reservation_rejects_guest_from_another_property(reservation_setup):
    property_, _, _, _, _ = reservation_setup
    other_organization = Organization.objects.create(name="Other", slug="other")
    other_property = Property.objects.create(
        organization=other_organization,
        name="Other Hotel",
        slug="other-hotel",
    )
    guest = Guest.objects.create(
        property=other_property,
        first_name="Other",
        email="other@example.com",
    )
    reservation = Reservation(
        property=property_,
        guest=guest,
        check_in=date(2026, 11, 1),
        check_out=date(2026, 11, 2),
    )

    with pytest.raises(ValidationError):
        reservation.full_clean()


@pytest.mark.django_db
def test_reservation_item_rejects_wrong_rate_plan_and_unit(reservation_setup):
    property_, unit_type, rate_plan, unit, guest = reservation_setup
    reservation = Reservation.objects.create(
        property=property_,
        guest=guest,
        check_in=date(2026, 11, 1),
        check_out=date(2026, 11, 2),
    )
    other_unit_type = UnitType.objects.create(
        property=property_,
        name="Suite",
        code="suite",
    )
    item = ReservationItem(
        reservation=reservation,
        unit_type=other_unit_type,
        rate_plan=rate_plan,
        unit=unit,
    )

    with pytest.raises(ValidationError):
        item.full_clean()


@pytest.mark.django_db
def test_reservation_rejects_invalid_dates(reservation_setup):
    property_, _, _, _, guest = reservation_setup
    reservation = Reservation(
        property=property_,
        guest=guest,
        check_in=date(2026, 11, 2),
        check_out=date(2026, 11, 2),
    )

    with pytest.raises(ValidationError):
        reservation.full_clean()


@pytest.mark.django_db
def test_reservation_item_check_in_and_check_out_are_recorded(reservation_setup):
    property_, unit_type, rate_plan, unit, guest = reservation_setup
    reservation = Reservation.objects.create(
        property=property_,
        guest=guest,
        check_in=date(2026, 11, 1),
        check_out=date(2026, 11, 3),
    )
    item = ReservationItem.objects.create(
        reservation=reservation,
        unit_type=unit_type,
        rate_plan=rate_plan,
        unit=unit,
    )
    check_in_at = datetime(2026, 11, 1, 14, 0, tzinfo=timezone.utc)
    check_out_at = datetime(2026, 11, 3, 10, 0, tzinfo=timezone.utc)

    item.check_in(at=check_in_at)
    item.refresh_from_db()
    assert item.stay_status == StayStatus.CHECKED_IN
    assert item.checked_in_at == check_in_at
    assert reservation.stay_status == StayStatus.CHECKED_IN

    item.check_out(at=check_out_at)
    item.refresh_from_db()
    assert item.stay_status == StayStatus.CHECKED_OUT
    assert item.checked_out_at == check_out_at
    assert reservation.stay_status == StayStatus.CHECKED_OUT


@pytest.mark.django_db
def test_check_out_requires_check_in(reservation_setup):
    property_, unit_type, rate_plan, unit, guest = reservation_setup
    reservation = Reservation.objects.create(
        property=property_,
        guest=guest,
        check_in=date(2026, 11, 1),
        check_out=date(2026, 11, 2),
    )
    item = ReservationItem.objects.create(
        reservation=reservation,
        unit_type=unit_type,
        rate_plan=rate_plan,
        unit=unit,
    )

    with pytest.raises(ValidationError):
        item.check_out()


@pytest.mark.django_db
def test_early_checkout_is_distinguished_from_normal_checkout(reservation_setup):
    property_, unit_type, rate_plan, unit, guest = reservation_setup
    reservation = Reservation.objects.create(
        property=property_,
        guest=guest,
        check_in=date(2026, 11, 1),
        check_out=date(2026, 11, 4),
    )
    item = ReservationItem.objects.create(
        reservation=reservation,
        unit_type=unit_type,
        rate_plan=rate_plan,
        unit=unit,
    )
    item.check_in(at=datetime(2026, 11, 1, 14, tzinfo=timezone.utc))
    item.check_out(
        at=datetime(2026, 11, 3, 9, tzinfo=timezone.utc),
        early=True,
    )

    assert item.stay_status == StayStatus.EARLY_CHECKOUT
    assert reservation.stay_status == StayStatus.EARLY_CHECKOUT

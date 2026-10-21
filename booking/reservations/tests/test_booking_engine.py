from datetime import date
from decimal import Decimal

import pytest
from django.test import RequestFactory
from booking.reservations.models import HoldStatus
from booking.reservations.models import ReservationHold
from booking.reservations.models import Reservation
from booking.reservations.models import ReservationChannel
from booking.reservations.models import ReservationSource
from booking.reservations.models import ReservationStatus
from booking.tenancy.models import DailyRate
from booking.tenancy.models import Inventory
from booking.tenancy.models import Organization
from booking.tenancy.models import Property
from booking.tenancy.models import RatePlan
from booking.tenancy.models import UnitType
from booking.reservations.services.booking import book_direct
from booking.reservations.views import widget_search


@pytest.fixture
def engine_setup():
    organization = Organization.objects.create(name="Balkans", slug="balkans-engine")
    property_ = Property.objects.create(
        organization=organization,
        name="Engine Hotel",
        slug="engine-hotel",
    )
    unit_type = UnitType.objects.create(
        property=property_,
        name="Standard Room",
        code="standard-room-engine",
    )
    rate_plan = RatePlan.objects.create(
        property=property_,
        unit_type=unit_type,
        name="Flexible",
        code="flexible-engine",
    )
    for day in (date(2026, 11, 1), date(2026, 11, 2)):
        Inventory.objects.create(
            property=property_,
            unit_type=unit_type,
            date=day,
            total_capacity=2,
        )
        DailyRate.objects.create(
            rate_plan=rate_plan,
            date=day,
            amount=Decimal("1500.00"),
        )
    return property_, rate_plan


@pytest.mark.django_db
def test_booking_engine_creates_hold_and_reservation(engine_setup):
    property_, rate_plan = engine_setup
    reservation = book_direct(
        property_id=property_.id,
        rate_plan_id=rate_plan.id,
        check_in=date(2026, 11, 1),
        check_out=date(2026, 11, 3),
        quantity=1,
        guest_data={
            "first_name": "Ada",
            "last_name": "Booking",
            "email": "ada@example.com",
            "phone": "+905551112233",
            "country": "TR",
        },
    )

    assert reservation.status == ReservationStatus.CONFIRMED
    assert reservation.total_amount == Decimal("3000.00")
    assert reservation.items.get().quantity == 1
    assert ReservationHold.objects.get(property=property_).status == HoldStatus.CONVERTED


@pytest.mark.django_db
def test_booking_engine_keeps_source_and_dynamic_channel(engine_setup):
    property_, rate_plan = engine_setup
    channel = ReservationChannel.objects.create(
        property=property_,
        code="phone",
        name="Telefon",
        source=ReservationSource.MANUAL,
    )
    reservation = book_direct(
        property_id=property_.id,
        rate_plan_id=rate_plan.id,
        check_in=date(2026, 11, 1),
        check_out=date(2026, 11, 3),
        quantity=1,
        guest_data={
            "first_name": "Phone",
            "last_name": "Booking",
            "email": "phone@example.com",
            "phone": "+905551112233",
            "country": "TR",
        },
        source=ReservationSource.MANUAL,
        channel=channel,
    )

    reservation.refresh_from_db()
    assert reservation.source == ReservationSource.MANUAL
    assert reservation.channel_id == channel.id


@pytest.mark.django_db
def test_widget_resolves_exact_channel_and_rejects_other_origin(engine_setup):
    property_, _ = engine_setup
    channel = ReservationChannel.objects.create(
        property=property_,
        code="hotel-site-widget",
        name="Hotel sitesi widget",
        source=ReservationSource.WIDGET,
        website_name="Hotel sitesi",
        website_domain="hotel.example",
    )

    allowed = RequestFactory().get(
        f"/booking/widget/{channel.widget_key}/",
        HTTP_REFERER="https://hotel.example/rezervasyon",
    )
    response = widget_search(allowed, channel.widget_key)
    assert response.status_code == 200
    assert b"Engine Hotel" in response.content

    denied = RequestFactory().get(
        f"/booking/widget/{channel.widget_key}/",
        HTTP_ORIGIN="https://other.example",
    )
    assert widget_search(denied, channel.widget_key).status_code == 403

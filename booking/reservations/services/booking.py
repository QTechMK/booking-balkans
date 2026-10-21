from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from booking.reservations.models import Guest
from booking.reservations.models import HoldStatus
from booking.reservations.models import Reservation
from booking.reservations.models import ReservationChannel
from booking.reservations.models import ReservationHold
from booking.reservations.models import ReservationItem
from booking.reservations.models import ReservationSource
from booking.reservations.models import ReservationStatus
from booking.reservations.services.holds import create_hold
from booking.tenancy.models import RatePlan


@transaction.atomic
def book_direct(
    *,
    property_id: int,
    rate_plan_id: int,
    check_in: date,
    check_out: date,
    quantity: int,
    guest_data: dict,
    source: str = ReservationSource.DIRECT,
    channel: ReservationChannel | None = None,
    created_by=None,
) -> Reservation:
    """Create a direct reservation after obtaining and converting a hold."""

    rate_plan = RatePlan.objects.select_related("unit_type").get(
        id=rate_plan_id,
        property_id=property_id,
        is_active=True,
    )
    hold, availability = create_hold(
        property_id=property_id,
        unit_type_id=rate_plan.unit_type_id,
        rate_plan_id=rate_plan.id,
        check_in=check_in,
        check_out=check_out,
        quantity=quantity,
        ttl_seconds=900,
    )
    if not availability.available:
        raise ValidationError("Selected room is no longer available.")

    guest = Guest.objects.create(property_id=property_id, **guest_data)
    reservation = Reservation.objects.create(
        property_id=property_id,
        guest=guest,
        status=ReservationStatus.CONFIRMED,
        source=source,
        channel=channel,
        created_by=created_by,
        check_in=check_in,
        check_out=check_out,
        currency=rate_plan.currency,
        subtotal_amount=availability.total_amount,
        total_amount=availability.total_amount,
        price_snapshot={
            "rate_plan": rate_plan.code,
            "currency": rate_plan.currency,
            "nightly": [str(day.amount) for day in availability.days],
            "quantity": quantity,
            "payment_method": "pay_at_property",
        },
    )
    ReservationItem.objects.create(
        reservation=reservation,
        unit_type=rate_plan.unit_type,
        rate_plan=rate_plan,
        quantity=quantity,
        adults=rate_plan.max_adults,
        nightly_amount=(
            availability.total_amount / Decimal(availability.nights) / quantity
        ),
        total_amount=availability.total_amount,
        price_snapshot=reservation.price_snapshot,
    )
    ReservationHold.objects.filter(pk=hold.pk).update(status=HoldStatus.CONVERTED)
    return reservation

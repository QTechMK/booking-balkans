from datetime import date
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from booking.tenancy.models import Inventory
from booking.tenancy.services.availability import AvailabilityResult
from booking.tenancy.services.availability import get_availability

from ..models import HoldStatus
from ..models import ReservationHold


class HoldUnavailable(Exception):
    """Raised when the requested capacity cannot be held."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(f"Capacity is not available: {reason}")


def expire_holds(*, now=None) -> int:
    """Mark active holds past their expiry as expired."""

    now = now or timezone.now()
    updated = ReservationHold.objects.filter(
        status=HoldStatus.ACTIVE,
        expires_at__lte=now,
    ).update(status=HoldStatus.EXPIRED)
    return updated


@transaction.atomic
def create_hold(
    *,
    property_id: int,
    unit_type_id: int,
    rate_plan_id: int,
    check_in: date,
    check_out: date,
    quantity: int = 1,
    ttl_seconds: int = 900,
    created_by=None,
) -> tuple[ReservationHold, AvailabilityResult]:
    """Lock inventory rows, verify availability, and create a temporary hold."""

    if quantity < 1:
        raise ValueError("quantity must be positive")
    if ttl_seconds < 1:
        raise ValueError("ttl_seconds must be positive")

    expire_holds()

    # Every capacity-writing path must lock the same daily inventory rows.
    # PostgreSQL enforces this lock; SQLite remains a development fallback.
    inventory_rows = list(
        Inventory.objects.select_for_update()
        .filter(
            property_id=property_id,
            unit_type_id=unit_type_id,
            date__gte=check_in,
            date__lt=check_out,
        )
        .order_by("date")
    )
    availability = get_availability(
        property_id=property_id,
        rate_plan_id=rate_plan_id,
        check_in=check_in,
        check_out=check_out,
        quantity=quantity,
    )
    if not availability.available:
        raise HoldUnavailable(availability.reason or "unavailable")

    hold = ReservationHold.objects.create(
        property_id=property_id,
        unit_type_id=unit_type_id,
        rate_plan_id=rate_plan_id,
        check_in=check_in,
        check_out=check_out,
        quantity=quantity,
        expires_at=timezone.now() + timedelta(seconds=ttl_seconds),
        created_by=created_by,
    )
    # Keep the local variable explicit so future PostgreSQL lock assertions do
    # not accidentally remove the row-locking query as an unused expression.
    if not inventory_rows:
        raise HoldUnavailable("inventory_missing")
    return hold, availability

from dataclasses import dataclass
from datetime import date
from datetime import timedelta
from decimal import Decimal

from django.db.models import QuerySet
from django.utils import timezone

from booking.tenancy.models import DailyRate
from booking.tenancy.models import Inventory
from booking.tenancy.models import RateRestriction
from booking.tenancy.models import RatePlan


@dataclass(frozen=True)
class AvailabilityDay:
    date: date
    amount: Decimal
    capacity: int


@dataclass(frozen=True)
class AvailabilityResult:
    available: bool
    check_in: date
    check_out: date
    nights: int
    total_amount: Decimal
    days: tuple[AvailabilityDay, ...]
    reason: str | None = None


def _nights(check_in: date, check_out: date) -> tuple[date, ...]:
    if check_out <= check_in:
        raise ValueError("check_out must be after check_in")
    return tuple(
        check_in + timedelta(days=offset)
        for offset in range((check_out - check_in).days)
    )


def _first_invalid_night_rule(
    nights: tuple[date, ...],
    rates: dict[date, DailyRate],
    restrictions: dict[date, RateRestriction],
) -> str | None:
    nights_count = len(nights)
    for night in nights:
        rate = rates.get(night)
        restriction = restrictions.get(night)
        if rate is None:
            return "rate_missing"
        if rate.is_closed:
            return "rate_closed"
        if nights_count < rate.min_nights:
            return "minimum_nights"
        if rate.max_nights is not None and nights_count > rate.max_nights:
            return "maximum_nights"
        if restriction is None:
            continue
        if restriction.stop_sell:
            return "stop_sell"
        if nights_count < restriction.min_nights:
            return "minimum_nights"
        if restriction.max_nights is not None and nights_count > restriction.max_nights:
            return "maximum_nights"

    arrival_restriction = restrictions.get(nights[0])
    if arrival_restriction and arrival_restriction.close_to_arrival:
        return "close_to_arrival"

    departure_restriction = restrictions.get(nights[-1])
    if departure_restriction and departure_restriction.close_to_departure:
        return "close_to_departure"

    return None


def get_availability(
    *,
    property_id: int,
    rate_plan_id: int,
    check_in: date,
    check_out: date,
    quantity: int = 1,
) -> AvailabilityResult:
    """Return a priced availability result for a rate plan and date range.

    Active reservations and non-expired holds are deducted from each night's
    sellable capacity. All write paths that create a reservation or hold must
    lock the matching inventory rows before calling this service.
    """

    if quantity < 1:
        raise ValueError("quantity must be positive")
    nights = _nights(check_in, check_out)
    rate_plan = RatePlan.objects.select_related("unit_type").filter(
        id=rate_plan_id,
        property_id=property_id,
        is_active=True,
    ).first()
    if rate_plan is None:
        return AvailabilityResult(
            available=False,
            check_in=check_in,
            check_out=check_out,
            nights=len(nights),
            total_amount=Decimal("0.00"),
            days=(),
            reason="rate_plan_unavailable",
        )

    inventory_rows: QuerySet[Inventory] = Inventory.objects.filter(
        property_id=property_id,
        unit_type_id=rate_plan.unit_type_id,
        date__gte=check_in,
        date__lt=check_out,
    )
    rate_rows: QuerySet[DailyRate] = DailyRate.objects.filter(
        rate_plan_id=rate_plan.id,
        date__gte=check_in,
        date__lt=check_out,
    )
    restriction_rows: QuerySet[RateRestriction] = RateRestriction.objects.filter(
        rate_plan_id=rate_plan.id,
        date__gte=check_in,
        date__lte=check_out,
    )

    inventories = {row.date: row for row in inventory_rows}
    rates = {row.date: row for row in rate_rows}
    restrictions = {row.date: row for row in restriction_rows}

    from booking.reservations.models import HoldStatus
    from booking.reservations.models import ReservationHold
    from booking.reservations.models import ReservationItem
    from booking.reservations.models import ReservationStatus

    reservation_items = ReservationItem.objects.filter(
        reservation__property_id=property_id,
        unit_type_id=rate_plan.unit_type_id,
        reservation__check_in__lt=check_out,
        reservation__check_out__gt=check_in,
        reservation__status__in=[
            ReservationStatus.PENDING,
            ReservationStatus.CONFIRMED,
        ],
    ).values_list("reservation__check_in", "reservation__check_out", "quantity")
    active_holds = ReservationHold.objects.filter(
        property_id=property_id,
        unit_type_id=rate_plan.unit_type_id,
        check_in__lt=check_out,
        check_out__gt=check_in,
        status=HoldStatus.ACTIVE,
        expires_at__gt=timezone.now(),
    ).values_list("check_in", "check_out", "quantity")

    def quantity_for_night(day: date, rows: list[tuple[date, date, int]]) -> int:
        return sum(
            row_quantity
            for row_check_in, row_check_out, row_quantity in rows
            if row_check_in <= day < row_check_out
        )

    reservation_rows = list(reservation_items)
    hold_rows = list(active_holds)

    for night in nights:
        inventory = inventories.get(night)
        if inventory is None:
            return AvailabilityResult(
                False, check_in, check_out, len(nights), Decimal("0.00"), (), "inventory_missing"
            )
        reserved_quantity = quantity_for_night(night, reservation_rows)
        held_quantity = quantity_for_night(night, hold_rows)
        available_capacity = inventory.sellable_capacity - reserved_quantity - held_quantity
        if inventory.is_closed or available_capacity < quantity:
            return AvailabilityResult(
                False, check_in, check_out, len(nights), Decimal("0.00"), (), "no_capacity"
            )

    invalid_reason = _first_invalid_night_rule(nights, rates, restrictions)
    if invalid_reason:
        return AvailabilityResult(
            False, check_in, check_out, len(nights), Decimal("0.00"), (), invalid_reason
        )

    days = tuple(
        AvailabilityDay(
            date=night,
            amount=rates[night].amount * quantity,
            capacity=(
                inventories[night].sellable_capacity
                - quantity_for_night(night, reservation_rows)
                - quantity_for_night(night, hold_rows)
            ),
        )
        for night in nights
    )
    return AvailabilityResult(
        available=True,
        check_in=check_in,
        check_out=check_out,
        nights=len(nights),
        total_amount=sum((day.amount for day in days), Decimal("0.00")),
        days=days,
    )

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.db import models
from django.utils import timezone

from booking.operations.models import ParkingLot, ParkingReservation, RentalExtraProduct, RentalInsurancePackage, RentalPricingRule, VehicleRentalBooking, VehicleRentalRate
from booking.tenancy.models import Vehicle


MONEY = Decimal("0.01")


@dataclass(frozen=True)
class RentalQuote:
    rental_days: int
    base_amount: Decimal
    discount_amount: Decimal
    extras_amount: Decimal
    insurance_amount: Decimal
    fees_amount: Decimal
    tax_amount: Decimal
    deposit_amount: Decimal
    total_amount: Decimal
    currency: str


def _money(value):
    return Decimal(value or 0).quantize(MONEY, rounding=ROUND_HALF_UP)


def _rental_days(pickup_at, dropoff_at):
    seconds = max((dropoff_at - pickup_at).total_seconds(), 0)
    return max(1, int((seconds + 86399) // 86400))


def _rate_amount(rate, rental_days):
    monthly = Decimal(rate.monthly_rate or 0)
    weekly = Decimal(rate.weekly_rate or 0)
    daily = Decimal(rate.daily_rate or 0)
    months, remainder = divmod(rental_days, 30)
    weeks, days = divmod(remainder, 7)
    if monthly and months:
        return monthly * months + (weekly * weeks if weekly else daily * (weeks * 7)) + daily * days
    if weekly and weeks:
        return weekly * weeks + daily * days
    return daily * rental_days


def calculate_parking_quote(*, parking_lot: ParkingLot, start_at: datetime, end_at: datetime):
    """Calculate a transparent parking amount using hourly/daily/night caps."""
    if not start_at or not end_at or end_at <= start_at:
        return Decimal("0.00")
    hours = max(1, int(((end_at - start_at).total_seconds() + 3599) // 3600))
    full_days, remaining_hours = divmod(hours, 24)
    daily = Decimal(parking_lot.daily_rate or 0)
    hourly = Decimal(parking_lot.hourly_rate or 0)
    daily_max = Decimal(parking_lot.daily_max_rate or 0)
    amount = daily * full_days + hourly * remaining_hours
    if daily_max:
        amount = min(amount, daily_max * (full_days + (1 if remaining_hours else 0)))
    night_rate = Decimal(parking_lot.night_rate or 0)
    night_start = parking_lot.night_start
    night_end = parking_lot.night_end
    if isinstance(night_start, str):
        night_start = time.fromisoformat(night_start)
    if isinstance(night_end, str):
        night_end = time.fromisoformat(night_end)
    if night_rate and night_start and night_end:
        cursor = start_at
        night_hours = 0
        while cursor < end_at:
            local_time = cursor.timetz().replace(tzinfo=None)
            in_night = (night_start <= local_time or local_time < night_end) if night_start > night_end else night_start <= local_time < night_end
            if in_night:
                night_hours += 1
            cursor += timedelta(hours=1)
        amount += night_rate * night_hours
    return _money(amount)


def calculate_rental_quote(*, rate: VehicleRentalRate, pickup_at: datetime, dropoff_at: datetime,
                           extra_product_ids=None, insurance_package_id=None, pickup_location=None,
                           dropoff_location=None, promo_code="", corporate_code="", loyalty_code="",
                           channel_code="", vehicle_class="", now=None):
    rental_days = _rental_days(pickup_at, dropoff_at)
    base_amount = _money(_rate_amount(rate, rental_days))
    now = now or timezone.now()
    booking_date = now.date() if hasattr(now, "date") else now
    discount_percent = Decimal("0")
    if (pickup_at.date() - booking_date).days >= 30:
        discount_percent += Decimal(rate.early_booking_percent or 0)
    if pickup_at.date() <= booking_date:
        discount_percent += Decimal(rate.last_minute_percent or 0)
    discount_amount = _money(base_amount * discount_percent / Decimal("100"))
    pricing_rules = RentalPricingRule.objects.filter(
        property=rate.vehicle.property, is_active=True, minimum_days__lte=rental_days,
    ).filter(models.Q(valid_from__isnull=True) | models.Q(valid_from__lte=booking_date)).filter(
        models.Q(valid_until__isnull=True) | models.Q(valid_until__gte=booking_date)
    ).order_by("priority", "id")
    for rule in pricing_rules:
        if rule.maximum_days and rental_days > rule.maximum_days:
            continue
        if rule.vehicle_class and rule.vehicle_class.lower() != (vehicle_class or rate.vehicle.vehicle_class).lower():
            continue
        if rule.channel_code and rule.channel_code.lower() != (channel_code or "").lower():
            continue
        if rule.promo_code and rule.promo_code.lower() != (promo_code or "").lower():
            continue
        if rule.corporate_code and rule.corporate_code.lower() != (corporate_code or "").lower():
            continue
        if rule.loyalty_code and rule.loyalty_code.lower() != (loyalty_code or "").lower():
            continue
        if rule.adjustment_type == RentalPricingRule.AdjustmentType.PERCENT:
            discount_amount += _money(base_amount * Decimal(rule.adjustment_amount or 0) / Decimal("100"))
        else:
            discount_amount += _money(rule.adjustment_amount)
        break

    extras = RentalExtraProduct.objects.filter(
        id__in=extra_product_ids or [], property=rate.vehicle.property, is_active=True,
    )
    extras_amount = sum((_money(item.price * rental_days if item.per_day else item.price) for item in extras), Decimal("0"))
    insurance_amount = Decimal("0")
    if insurance_package_id:
        package = RentalInsurancePackage.objects.filter(
            id=insurance_package_id, property=rate.vehicle.property, is_active=True,
        ).first()
        if package:
            insurance_amount = _money(package.price * rental_days if package.per_day else package.price)

    fees_amount = Decimal(rate.service_fee or 0) + Decimal(rate.airport_fee or 0)
    if pickup_location:
        fees_amount += Decimal(pickup_location.pickup_fee or 0)
    if dropoff_location:
        fees_amount += Decimal(dropoff_location.dropoff_fee or 0)
    fees_amount = _money(fees_amount)
    taxable = base_amount - discount_amount + extras_amount + insurance_amount + fees_amount
    tax_percent = Decimal(rate.vat_percent or 0) + Decimal(rate.special_consumption_tax_percent or 0)
    tax_amount = _money(taxable * tax_percent / Decimal("100"))
    total_amount = _money(taxable + tax_amount)
    return RentalQuote(
        rental_days=rental_days,
        base_amount=base_amount,
        discount_amount=discount_amount,
        extras_amount=_money(extras_amount),
        insurance_amount=_money(insurance_amount),
        fees_amount=fees_amount,
        tax_amount=tax_amount,
        deposit_amount=_money(rate.deposit_amount),
        total_amount=total_amount,
        currency=rate.currency,
    )


def available_rental_vehicles(*, property_, pickup_at=None, dropoff_at=None, vehicle_class=""):
    vehicles = Vehicle.objects.filter(property=property_, is_active=True, online_enabled=True)
    if vehicle_class:
        vehicles = vehicles.filter(vehicle_class__iexact=vehicle_class)
    if pickup_at and dropoff_at:
        occupied = VehicleRentalBooking.objects.filter(
            vehicle_id__in=vehicles.values("id"),
            pickup_at__lt=dropoff_at,
            dropoff_at__gt=pickup_at,
            status__in=[VehicleRentalBooking.Status.PENDING, VehicleRentalBooking.Status.CONFIRMED, VehicleRentalBooking.Status.ACTIVE],
        ).values("vehicle_id")
        vehicles = vehicles.exclude(id__in=occupied)
    return vehicles


def available_parking_spaces(*, property_, start_at=None, end_at=None, parking_lot_id=None):
    from booking.operations.models import ParkingSpace

    spaces = ParkingSpace.objects.filter(
        parking_lot__property=property_, parking_lot__is_active=True,
        parking_lot__booking_enabled=True, is_active=True,
        status=ParkingSpace.Status.AVAILABLE,
    )
    if parking_lot_id:
        spaces = spaces.filter(parking_lot_id=parking_lot_id)
    if start_at and end_at:
        occupied = ParkingReservation.objects.filter(
            parking_space_id__in=spaces.values("id"),
            start_at__lt=end_at,
            end_at__gt=start_at,
            status__in=[ParkingReservation.Status.PENDING, ParkingReservation.Status.CONFIRMED, ParkingReservation.Status.CHECKED_IN],
        ).values("parking_space_id")
        spaces = spaces.exclude(id__in=occupied)
    return spaces

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from ..models import DepositHold, RentalAuditEvent, RentalPayment, VehicleRentalBooking
from .rental_payments import create_pending_rental_payment


@transaction.atomic
def create_deposit_hold(*, booking: VehicleRentalBooking, amount=None, gateway=None, actor=None):
    """Create one local deposit hold; provider authorization is performed separately."""
    value = Decimal(amount if amount is not None else booking.deposit_amount or 0)
    if value <= 0:
        return None
    hold = DepositHold.objects.select_for_update().filter(booking=booking).first()
    if hold:
        return hold
    payment = create_pending_rental_payment(
        booking=booking, amount=value, gateway=gateway, preauthorization=True,
    )
    hold = DepositHold.objects.create(
        booking=booking, payment=payment, amount=value, currency=booking.currency,
        status=DepositHold.Status.HELD,
        metadata={"source": booking.source, "confirmation_code": booking.confirmation_code},
    )
    RentalAuditEvent.objects.create(
        property=booking.property, booking=booking, actor=actor,
        action="deposit_held", source="system",
        payload={"deposit_hold_id": hold.id, "amount": str(value), "currency": booking.currency},
    )
    return hold


@transaction.atomic
def release_deposit_hold(*, hold: DepositHold, actor=None):
    hold = DepositHold.objects.select_for_update().select_related("booking").get(pk=hold.pk)
    if hold.status == DepositHold.Status.RELEASED:
        return hold
    if hold.status not in {DepositHold.Status.HELD, DepositHold.Status.PARTIALLY_CAPTURED}:
        raise ValidationError("Bu depozito durumu serbest bırakmaya uygun değil.")
    hold.status = DepositHold.Status.RELEASED
    hold.released_at = timezone.now()
    hold.save(update_fields=["status", "released_at", "updated_at"])
    if hold.payment_id and hold.payment.status in {RentalPayment.Status.PENDING, RentalPayment.Status.AUTHORIZED}:
        hold.payment.status = RentalPayment.Status.REFUNDED
        hold.payment.save(update_fields=["status", "updated_at"])
    RentalAuditEvent.objects.create(
        property=hold.booking.property, booking=hold.booking, actor=actor,
        action="deposit_released", source="system", payload={"deposit_hold_id": hold.id},
    )
    return hold


@transaction.atomic
def capture_deposit_hold(*, hold: DepositHold, amount, actor=None, forfeited=False):
    hold = DepositHold.objects.select_for_update().select_related("booking").get(pk=hold.pk)
    value = Decimal(amount)
    remaining = hold.amount - hold.captured_amount
    if value <= 0 or value > remaining:
        raise ValidationError("Depozito tahsilatı kalan tutarı aşamaz.")
    hold.captured_amount += value
    hold.status = DepositHold.Status.FORFEITED if forfeited and hold.captured_amount == hold.amount else (
        DepositHold.Status.CAPTURED if hold.captured_amount == hold.amount else DepositHold.Status.PARTIALLY_CAPTURED
    )
    hold.save(update_fields=["captured_amount", "status", "updated_at"])
    RentalAuditEvent.objects.create(
        property=hold.booking.property, booking=hold.booking, actor=actor,
        action="deposit_captured", source="system",
        payload={"deposit_hold_id": hold.id, "amount": str(value), "status": hold.status},
    )
    return hold

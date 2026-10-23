from decimal import Decimal

from booking.operations.models import RentalPayment, VehicleRentalBooking


def create_pending_rental_payment(*, booking: VehicleRentalBooking, amount=None, gateway=None, preauthorization=False):
    """Create a safe pending payment intent; provider adapters capture it later."""
    value = Decimal(amount if amount is not None else booking.prepayment_amount or booking.total_amount or 0)
    if value <= 0:
        return None
    existing = booking.payments.filter(status=RentalPayment.Status.PENDING, amount=value, is_preauthorization=preauthorization).first()
    if existing:
        return existing
    return RentalPayment.objects.create(
        booking=booking, gateway=gateway, amount=value, currency=booking.currency,
        status=RentalPayment.Status.PENDING, is_preauthorization=preauthorization,
        metadata={"source": booking.source, "confirmation_code": booking.confirmation_code},
    )

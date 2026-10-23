from types import SimpleNamespace

from django.db import transaction

from booking.reservations.services.payments import PaymentConfigurationError, PaymentProviderError, create_checkout
from booking.reservations.services.bank_payments import build_cpay_checkout, build_nestpay_checkout

from booking.operations.models import RentalPayment, VehicleRentalBooking


@transaction.atomic
def start_rental_checkout(*, booking: VehicleRentalBooking, gateway, success_url: str, cancel_url: str):
    """Start a provider checkout and persist its external reference atomically."""
    amount = booking.prepayment_amount or booking.total_amount
    if not amount or amount <= 0:
        raise PaymentProviderError("Rental payment amount must be greater than zero.")
    provider = (gateway.payment_model or "").strip().lower()
    if provider not in {"stripe", "paypal", "nestpay_halkbank", "cpay_stb"}:
        raise PaymentConfigurationError("Unsupported rental payment gateway.")
    payment = booking.payments.filter(status=RentalPayment.Status.PENDING, amount=amount).first()
    if not payment:
        payment = RentalPayment.objects.create(
            booking=booking, gateway=gateway, amount=amount,
            currency=booking.currency, status=RentalPayment.Status.PENDING,
        )
    reference = SimpleNamespace(reference=booking.confirmation_code, currency=booking.currency)
    if provider == "nestpay_halkbank":
        result = build_nestpay_checkout(
            gateway=gateway, reservation=reference, amount=amount,
            success_url=success_url, cancel_url=cancel_url,
        )
    elif provider == "cpay_stb":
        result = build_cpay_checkout(
            gateway=gateway, reservation=reference, amount=amount,
            success_url=success_url, cancel_url=cancel_url,
        )
    else:
        result = create_checkout(provider=provider, reservation=reference, amount=amount, success_url=success_url, cancel_url=cancel_url)
    payment.status = RentalPayment.Status.PENDING if result.get("checkout_method") == "post" else RentalPayment.Status.AUTHORIZED
    payment.provider_reference = result["external_id"]
    payment.metadata = {"provider": provider, **result.get("payload", {})}
    payment.save(update_fields=["status", "provider_reference", "metadata", "updated_at"])
    return payment, result

from django.conf import settings
from django.db import transaction
from django.utils import timezone

import requests

from booking.reservations.services.payments import PaymentConfigurationError, PaymentProviderError, capture_paypal_order

from booking.operations.models import RentalAuditEvent, RentalPayment


def _stripe_request(method, path, **kwargs):
    secret = getattr(settings, "PAYMENT_STRIPE_SECRET_KEY", "")
    if not secret:
        raise PaymentConfigurationError("Stripe secret key is not configured.")
    response = requests.request(
        method,
        f"https://api.stripe.com{path}",
        headers={"Authorization": f"Bearer {secret}"},
        timeout=15,
        **kwargs,
    )
    if not response.ok:
        raise PaymentProviderError(f"Stripe request failed: HTTP {response.status_code}")
    return response.json()


def _stripe_payment_intent(payment):
    session_id = payment.provider_reference
    if not session_id:
        raise PaymentProviderError("Stripe checkout session reference is missing.")
    session = _stripe_request("GET", f"/v1/checkout/sessions/{session_id}")
    intent = session.get("payment_intent")
    if not intent:
        raise PaymentProviderError("Stripe checkout has no payment intent yet.")
    return intent


@transaction.atomic
def capture_rental_payment(*, payment: RentalPayment, actor=None):
    """Capture a provider authorization and only then mark the local payment captured."""
    if payment.status == RentalPayment.Status.CAPTURED:
        return payment
    if payment.status not in {RentalPayment.Status.PENDING, RentalPayment.Status.AUTHORIZED}:
        raise PaymentProviderError("Only pending or authorized payments can be captured.")
    provider = (payment.gateway.payment_model if payment.gateway else "").strip().lower()
    if provider == "paypal":
        payload = capture_paypal_order(payment.provider_reference)
    elif provider == "stripe":
        raise PaymentProviderError("Stripe checkout payments are captured by the signed webhook.")
    else:
        raise PaymentConfigurationError("A supported payment gateway is required for capture.")
    payment.status = RentalPayment.Status.CAPTURED
    payment.metadata = {**(payment.metadata or {}), "capture": payload}
    payment.save(update_fields=["status", "metadata", "updated_at"])
    RentalAuditEvent.objects.create(
        property=payment.booking.property,
        booking=payment.booking,
        actor=actor,
        action="payment_captured",
        source="admin",
        payload={"payment_id": payment.id, "provider": provider, "provider_reference": payment.provider_reference},
    )
    return payment


@transaction.atomic
def refund_rental_payment(*, payment: RentalPayment, actor=None):
    """Refund a captured payment through the provider before changing local state."""
    if payment.status == RentalPayment.Status.REFUNDED:
        return payment
    if payment.status != RentalPayment.Status.CAPTURED:
        raise PaymentProviderError("Only captured payments can be refunded.")
    provider = (payment.gateway.payment_model if payment.gateway else "").strip().lower()
    if provider == "stripe":
        intent = _stripe_payment_intent(payment)
        payload = _stripe_request("POST", "/v1/refunds", data={"payment_intent": intent})
        if payload.get("status") not in {"succeeded", "pending"}:
            raise PaymentProviderError("Stripe refund was not accepted.")
    elif provider == "paypal":
        capture_id = ((payment.metadata or {}).get("capture", {}).get("purchase_units", [{}])[0]
                      .get("payments", {}).get("captures", [{}])[0].get("id"))
        if not capture_id:
            raise PaymentProviderError("PayPal capture reference is missing for refund.")
        payload = _paypal_refund(capture_id, payment.amount, payment.currency)
    else:
        raise PaymentConfigurationError("A supported payment gateway is required for refund.")
    payment.status = RentalPayment.Status.REFUNDED
    payment.metadata = {**(payment.metadata or {}), "refund": payload}
    payment.save(update_fields=["status", "metadata", "updated_at"])
    RentalAuditEvent.objects.create(
        property=payment.booking.property,
        booking=payment.booking,
        actor=actor,
        action="payment_refunded",
        source="admin",
        payload={"payment_id": payment.id, "provider": provider, "provider_reference": payment.provider_reference},
    )
    return payment


@transaction.atomic
def record_manual_bank_refund(*, payment: RentalPayment, refund_reference: str, note: str = "", actor=None):
    """Record a refund completed in a NestPay/cPay bank panel without calling the bank API."""
    if payment.status == RentalPayment.Status.REFUNDED:
        return payment
    if payment.status != RentalPayment.Status.CAPTURED:
        raise PaymentProviderError("Only captured payments can be refunded.")
    provider = (payment.gateway.payment_model if payment.gateway else "").strip().lower()
    if provider not in {"nestpay_halkbank", "cpay_stb"}:
        raise PaymentConfigurationError("Manual bank refund is only available for Halkbank/cPay gateways.")
    reference = (refund_reference or "").strip()
    if not reference:
        raise PaymentProviderError("The bank refund reference is required.")
    payment.status = RentalPayment.Status.REFUNDED
    payment.metadata = {**(payment.metadata or {}), "refund": {
        "mode": "manual_bank_panel", "reference": reference, "note": note.strip(),
        "recorded_at": timezone.now().isoformat(),
    }}
    payment.save(update_fields=["status", "metadata", "updated_at"])
    RentalAuditEvent.objects.create(
        property=payment.booking.property, booking=payment.booking, actor=actor,
        action="payment_refunded_manual", source="bank_panel",
        payload={"payment_id": payment.id, "provider": provider, "refund_reference": reference},
    )
    return payment


def _paypal_refund(capture_id, amount, currency):
    client_id = getattr(settings, "PAYMENT_PAYPAL_CLIENT_ID", "")
    client_secret = getattr(settings, "PAYMENT_PAYPAL_CLIENT_SECRET", "")
    base_url = getattr(settings, "PAYMENT_PAYPAL_BASE_URL", "https://api-m.sandbox.paypal.com").rstrip("/")
    if not client_id or not client_secret:
        raise PaymentConfigurationError("PayPal credentials are not configured.")
    token_response = requests.post(
        f"{base_url}/v1/oauth2/token", auth=(client_id, client_secret),
        headers={"Accept": "application/json", "Accept-Language": "en_US"},
        data={"grant_type": "client_credentials"}, timeout=15,
    )
    if not token_response.ok:
        raise PaymentProviderError(f"PayPal authentication failed: HTTP {token_response.status_code}")
    token = token_response.json().get("access_token")
    response = requests.post(
        f"{base_url}/v2/payments/captures/{capture_id}/refund",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"amount": {"value": f"{amount:.2f}", "currency_code": currency}}, timeout=15,
    )
    if not response.ok:
        raise PaymentProviderError(f"PayPal refund failed: HTTP {response.status_code}")
    return response.json()

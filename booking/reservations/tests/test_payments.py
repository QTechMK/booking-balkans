import hashlib
import hmac
import json
from datetime import date
from decimal import Decimal

import pytest
from django.test import RequestFactory

from booking.reservations.models import Guest, PaymentTransaction, Reservation
from booking.reservations.services.payments import capture_paypal_order, create_checkout
from booking.reservations.views import stripe_webhook
from booking.tenancy.models import Organization, Property


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code
        self.ok = status_code < 400

    def json(self):
        return self.payload


@pytest.fixture
def payment_reservation():
    organization = Organization.objects.create(name="Hotel Group", slug="hotel-group")
    property_ = Property.objects.create(organization=organization, name="Main Hotel", slug="main-hotel")
    guest = Guest.objects.create(property=property_, first_name="Ada", email="ada@example.com")
    return Reservation.objects.create(
        property=property_, guest=guest, check_in=date(2026, 11, 1), check_out=date(2026, 11, 2),
        currency="EUR", total_amount=Decimal("120.00"), subtotal_amount=Decimal("120.00"),
    )


@pytest.mark.django_db
def test_stripe_checkout_requires_secret(payment_reservation, settings):
    settings.PAYMENT_STRIPE_SECRET_KEY = ""
    with pytest.raises(RuntimeError, match="secret key"):
        create_checkout(provider="stripe", reservation=payment_reservation, amount=Decimal("20"), success_url="https://ok", cancel_url="https://cancel")


@pytest.mark.django_db
def test_stripe_checkout_returns_session(payment_reservation, settings, monkeypatch):
    settings.PAYMENT_STRIPE_SECRET_KEY = "sk_test"
    monkeypatch.setattr("booking.reservations.services.payments.requests.post", lambda *args, **kwargs: FakeResponse({"id": "cs_123", "url": "https://checkout"}))
    result = create_checkout(provider="stripe", reservation=payment_reservation, amount=Decimal("20.00"), success_url="https://ok", cancel_url="https://cancel")
    assert result["external_id"] == "cs_123"
    assert result["checkout_url"] == "https://checkout"


@pytest.mark.django_db
def test_stripe_webhook_marks_transaction_paid(payment_reservation, settings):
    settings.PAYMENT_STRIPE_WEBHOOK_SECRET = "whsec_test"
    transaction = PaymentTransaction.objects.create(
        reservation=payment_reservation, provider="stripe", amount=Decimal("20.00"), currency="EUR", external_id="cs_123",
    )
    body = json.dumps({"type": "checkout.session.completed", "data": {"object": {"id": "cs_123"}}}).encode()
    timestamp = "1700000000"
    digest = hmac.new(settings.PAYMENT_STRIPE_WEBHOOK_SECRET.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()
    request = RequestFactory().post("/booking/webhooks/stripe/", data=body, content_type="application/json", HTTP_STRIPE_SIGNATURE=f"t={timestamp},v1={digest}")
    response = stripe_webhook(request)
    transaction.refresh_from_db()
    assert response.status_code == 200
    assert transaction.status == PaymentTransaction.Status.PAID


@pytest.mark.django_db
def test_paypal_capture_requires_completed_status(settings, monkeypatch):
    settings.PAYMENT_PAYPAL_CLIENT_ID = "client"
    settings.PAYMENT_PAYPAL_CLIENT_SECRET = "secret"
    responses = iter([FakeResponse({"access_token": "token"}), FakeResponse({"status": "COMPLETED"})])
    monkeypatch.setattr("booking.reservations.services.payments.requests.post", lambda *args, **kwargs: next(responses))
    assert capture_paypal_order("order-1")["status"] == "COMPLETED"

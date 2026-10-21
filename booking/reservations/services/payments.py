from decimal import Decimal, ROUND_HALF_UP

import requests
from django.conf import settings


class PaymentConfigurationError(RuntimeError):
    pass


class PaymentProviderError(RuntimeError):
    pass


def _minor_units(amount: Decimal) -> int:
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def create_checkout(*, provider, reservation, amount, success_url, cancel_url):
    if amount <= 0:
        raise PaymentProviderError("Payment amount must be greater than zero.")
    if provider == "stripe":
        return _stripe_checkout(reservation, amount, success_url, cancel_url)
    if provider == "paypal":
        return _paypal_checkout(reservation, amount, success_url, cancel_url)
    raise PaymentConfigurationError("Unsupported payment provider.")


def _stripe_checkout(reservation, amount, success_url, cancel_url):
    secret = getattr(settings, "PAYMENT_STRIPE_SECRET_KEY", "")
    if not secret:
        raise PaymentConfigurationError("Stripe secret key is not configured.")
    response = requests.post(
        "https://api.stripe.com/v1/checkout/sessions",
        headers={"Authorization": f"Bearer {secret}"},
        data={
            "mode": "payment",
            "success_url": success_url,
            "cancel_url": cancel_url,
            "client_reference_id": reservation.reference,
            "line_items[0][quantity]": 1,
            "line_items[0][price_data][currency]": reservation.currency.lower(),
            "line_items[0][price_data][unit_amount]": _minor_units(amount),
            "line_items[0][price_data][product_data][name]": f"Reservation {reservation.reference}",
        },
        timeout=15,
    )
    if not response.ok:
        raise PaymentProviderError(f"Stripe checkout failed: HTTP {response.status_code}")
    payload = response.json()
    if not payload.get("id") or not payload.get("url"):
        raise PaymentProviderError("Stripe returned an incomplete checkout response.")
    return {"external_id": payload["id"], "checkout_url": payload["url"], "payload": payload}


def _paypal_checkout(reservation, amount, success_url, cancel_url):
    client_id = getattr(settings, "PAYMENT_PAYPAL_CLIENT_ID", "")
    client_secret = getattr(settings, "PAYMENT_PAYPAL_CLIENT_SECRET", "")
    base_url = getattr(settings, "PAYMENT_PAYPAL_BASE_URL", "https://api-m.sandbox.paypal.com").rstrip("/")
    if not client_id or not client_secret:
        raise PaymentConfigurationError("PayPal credentials are not configured.")
    token_response = requests.post(
        f"{base_url}/v1/oauth2/token",
        auth=(client_id, client_secret),
        headers={"Accept": "application/json", "Accept-Language": "en_US"},
        data={"grant_type": "client_credentials"},
        timeout=15,
    )
    if not token_response.ok:
        raise PaymentProviderError(f"PayPal authentication failed: HTTP {token_response.status_code}")
    token = token_response.json().get("access_token")
    if not token:
        raise PaymentProviderError("PayPal returned no access token.")
    order_response = requests.post(
        f"{base_url}/v2/checkout/orders",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={
            "intent": "CAPTURE",
            "purchase_units": [{"reference_id": reservation.reference, "amount": {"currency_code": reservation.currency, "value": f"{amount:.2f}"}}],
            "application_context": {"return_url": success_url, "cancel_url": cancel_url},
        },
        timeout=15,
    )
    if not order_response.ok:
        raise PaymentProviderError(f"PayPal order failed: HTTP {order_response.status_code}")
    payload = order_response.json()
    approve_url = next((link.get("href") for link in payload.get("links", []) if link.get("rel") == "approve"), "")
    if not payload.get("id") or not approve_url:
        raise PaymentProviderError("PayPal returned an incomplete order response.")
    return {"external_id": payload["id"], "checkout_url": approve_url, "payload": payload}


def capture_paypal_order(external_id):
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
    if not token:
        raise PaymentProviderError("PayPal returned no access token.")
    response = requests.post(
        f"{base_url}/v2/checkout/orders/{external_id}/capture",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        timeout=15,
    )
    if not response.ok:
        raise PaymentProviderError(f"PayPal capture failed: HTTP {response.status_code}")
    payload = response.json()
    if payload.get("status") != "COMPLETED":
        raise PaymentProviderError("PayPal capture was not completed.")
    return payload

"""Hosted 3-D Secure form builders for the supported bank gateways.

Card data never enters Booking Balkans. The browser posts the signed form
directly to the provider, and the provider posts the result back to us.
Secrets are read from environment-backed Django settings or a configured
environment-variable name; they are never stored in the tenant database.
"""

import base64
import hashlib
import hmac
import html
import os
import time
from decimal import Decimal

from django.conf import settings

from .payments import PaymentConfigurationError


def _config(gateway, key, setting_name, default=""):
    value = (gateway.configuration or {}).get(key, "")
    if value:
        return os.environ.get(value, value) if key.endswith("_env") else value
    return getattr(settings, setting_name, default)


def _amount(amount):
    return f"{Decimal(amount):.2f}"


def _form_response(url, fields, method="post"):
    inputs = "".join(
        f'<input type="hidden" name="{html.escape(str(name))}" value="{html.escape(str(value), quote=True)}">'
        for name, value in fields.items()
        if value is not None
    )
    action = html.escape(url, quote=True)
    body = (
        '<!doctype html><html><head><meta charset="utf-8"><title>Güvenli ödeme</title></head>'
        f'<body><form id="payment-form" method="{method}" action="{action}">{inputs}'
        '<noscript><button type="submit">Ödemeye devam et</button></noscript></form>'
        '<script>document.getElementById("payment-form").submit();</script></body></html>'
    )
    return body


def _nestpay_hash(fields, store_key):
    # NestPay/Asseco signs the documented field order. The card fields are
    # intentionally empty because card entry happens on the hosted page.
    ordered = [
        "amount", "clientid", "currency", "failUrl", "hashAlgorithm",
        "instalment", "lang", "oid", "okUrl", "refreshtime", "rnd",
        "storetype", "trantype",
    ]
    raw = "|".join(str(fields.get(name, "")) for name in ordered) + "|" + store_key
    return base64.b64encode(hashlib.sha512(raw.encode("utf-8")).digest()).decode("ascii")


def build_nestpay_checkout(*, gateway, reservation, amount, success_url, cancel_url):
    client_id = gateway.merchant_id or _config(gateway, "client_id_env", "PAYMENT_NESTPAY_CLIENT_ID")
    store_key = _config(gateway, "store_key_env", "PAYMENT_NESTPAY_STORE_KEY")
    post_url = gateway.endpoint_url or _config(gateway, "post_url", "PAYMENT_NESTPAY_POST_URL")
    if not client_id or not store_key or not post_url:
        raise PaymentConfigurationError("Halkbank/Asseco NestPay ayarları tamamlanmamış.")
    fields = {
        "amount": _amount(amount), "clientid": client_id,
        "currency": (gateway.currency or "TRY").upper(),
        "failUrl": cancel_url, "hashAlgorithm": "ver3",
        "instalment": "", "lang": (gateway.configuration or {}).get("lang", "tr"),
        "oid": reservation.reference, "okUrl": success_url,
        "refreshtime": "5", "rnd": str(int(time.time())),
        "storetype": "3d_pay", "trantype": "Auth",
    }
    fields["hash"] = _nestpay_hash(fields, store_key)
    return {
        "external_id": reservation.reference, "checkout_url": post_url,
        "checkout_method": "post", "form_fields": fields, "payload": fields,
    }


def _cpay_header(parameters):
    names = ",".join(parameters) + ","
    lengths = "".join(f"{len(str(value)):03d}" for value in parameters.values())
    return f"{len(parameters):02d}{names}{lengths}"


def _cpay_checksum(parameters, password):
    header = _cpay_header(parameters)
    names = header[2:].split(",")[:-1]
    values = "".join(str(parameters.get(name, "")) for name in names)
    return header, hmac.new(password.encode("utf-8"), (header + values).encode("utf-8"), hashlib.sha256).hexdigest()


def build_cpay_checkout(*, gateway, reservation, amount, success_url, cancel_url):
    config = gateway.configuration or {}
    merchant_id = gateway.merchant_id or _config(gateway, "merchant_id_env", "PAYMENT_CPAY_MERCHANT_ID")
    merchant_name = config.get("merchant_name") or _config(gateway, "merchant_name_env", "PAYMENT_CPAY_MERCHANT_NAME")
    password = _config(gateway, "merchant_password_env", "PAYMENT_CPAY_MERCHANT_PASSWORD")
    payment_url = gateway.endpoint_url or _config(gateway, "payment_url", "PAYMENT_CPAY_PAYMENT_URL")
    if not merchant_id or not merchant_name or not password or not payment_url:
        raise PaymentConfigurationError("cPay/STB ayarları tamamlanmamış.")
    parameters = {
        "AmountToPay": str(int(Decimal(amount) * 100)),
        "PayToMerchant": merchant_id, "MerchantName": merchant_name,
        "AmountCurrency": (gateway.currency or "TRY").upper(),
        "PaymentOKURL": success_url, "PaymentFailURL": cancel_url,
        "Details1": reservation.reference, "Details2": str(int(time.time())),
        "Discount": "",
    }
    header, checksum = _cpay_checksum(parameters, password)
    fields = {**parameters, "CheckSumHeader": header, "CheckSum": checksum}
    return {
        "external_id": reservation.reference, "checkout_url": payment_url,
        "checkout_method": "post", "form_fields": fields, "payload": fields,
    }


def verify_nestpay_response(post_data, store_key):
    response = str(post_data.get("Response", ""))
    if response != "Approved" or str(post_data.get("mdStatus", "")) not in {"1", "2", "3", "4"}:
        return False
    params = str(post_data.get("HASHPARAMS", ""))
    received = str(post_data.get("HASH", ""))
    if not params or not received or not store_key:
        return False
    raw = "".join(str(post_data.get(name, "")) for name in params.split(":") if name) + store_key
    expected = base64.b64encode(hashlib.sha512(raw.encode("utf-8")).digest()).decode("ascii")
    return hmac.compare_digest(expected, received)


def verify_cpay_response(post_data, password):
    received = str(post_data.get("ReturnCheckSum", ""))
    header = str(post_data.get("ReturnCheckSumHeader", ""))
    if not received or not header or not password:
        return False
    names = header[2:].split(",")[:-1]
    raw = header + "".join(str(post_data.get(name, "")) for name in names)
    expected = hmac.new(password.encode("utf-8"), raw.encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected.lower(), received.lower())


def render_checkout(result):
    return _form_response(result["checkout_url"], result["form_fields"], result.get("checkout_method", "post"))

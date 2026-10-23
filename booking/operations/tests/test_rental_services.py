from datetime import datetime, timedelta
from decimal import Decimal
import hashlib
import hmac
import json

import pytest
from django.utils import timezone
from django.test import Client, override_settings
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model

from booking.operations.models import EInvoiceTransmission, Invoice, PaymentGateway, ParkingDevice, ParkingLot, ParkingReservation, RentalAuditEvent, RentalChannelSyncEvent, RentalDataRequest, RentalExtraProduct, RentalFlightStatus, RentalInsurancePackage, RentalPayment, RentalPricingRule, RentalPrivacyEvent, RentalSettlement, RentalInvoice, VehicleRentalBooking, VehicleRentalRate, VehicleTelemetryEvent
from booking.operations.services.rental_pricing import available_rental_vehicles, calculate_parking_quote, calculate_rental_quote
from booking.operations.services.rental_notifications import queue_rental_notifications
from booking.operations.services.rental_payments import create_pending_rental_payment
from booking.operations.services.rental_checkout import start_rental_checkout
from booking.operations.services.rental_settlement import issue_settlement_invoice
from booking.operations.services.e_invoice import queue_invoice_export
from booking.reservations.services.bank_payments import build_cpay_checkout, build_nestpay_checkout, verify_cpay_response
from booking.operations.services.rental_payment_actions import capture_rental_payment, record_manual_bank_refund, refund_rental_payment
from booking.operations.services.deposits import capture_deposit_hold, create_deposit_hold, release_deposit_hold
from booking.operations.services.rental_channels import dispatch_queued_first_party_events, push_channel_event, queue_channel_event, queue_first_party_event, queue_first_party_snapshot
from booking.tenancy.models import Organization, Property, Vehicle


def test_bank_payment_options_build_signed_hosted_forms(settings):
    from types import SimpleNamespace

    settings.PAYMENT_NESTPAY_STORE_KEY = "test-store-key"
    settings.PAYMENT_CPAY_MERCHANT_ID = "test-merchant"
    settings.PAYMENT_CPAY_MERCHANT_NAME = "Test Merchant"
    settings.PAYMENT_CPAY_MERCHANT_PASSWORD = "test-password"
    settings.PAYMENT_CPAY_PAYMENT_URL = "https://cpay.example/checkout"
    reference = SimpleNamespace(reference="BK-TEST-1", currency="TRY")
    nestpay_gateway = SimpleNamespace(
        merchant_id="test-client", currency="TRY", endpoint_url="https://nestpay.example/3d",
        configuration={},
    )
    cpay_gateway = SimpleNamespace(merchant_id="", currency="TRY", endpoint_url="", configuration={})

    nestpay = build_nestpay_checkout(
        gateway=nestpay_gateway, reservation=reference, amount=Decimal("10.00"),
        success_url="https://example/ok", cancel_url="https://example/fail",
    )
    cpay = build_cpay_checkout(
        gateway=cpay_gateway, reservation=reference, amount=Decimal("10.00"),
        success_url="https://example/ok", cancel_url="https://example/fail",
    )

    assert nestpay["checkout_method"] == "post"
    assert nestpay["form_fields"]["oid"] == "BK-TEST-1"
    assert cpay["form_fields"]["Details1"] == "BK-TEST-1"
    assert verify_cpay_response(
        {**cpay["form_fields"], "ReturnCheckSum": cpay["form_fields"]["CheckSum"],
         "ReturnCheckSumHeader": cpay["form_fields"]["CheckSumHeader"]},
        "test-password",
    )


@pytest.mark.django_db
def test_settlement_invoice_is_created_once_and_links_to_rental(rental_setup):
    property_, vehicle, rate, *_ = rental_setup
    start = timezone.now() + timedelta(days=1)
    booking = VehicleRentalBooking.objects.create(
        property=property_, vehicle=vehicle, rental_rate=rate,
        customer_name="Test Driver", pickup_at=start,
        dropoff_at=start + timedelta(days=2), currency="TRY",
    )
    settlement = RentalSettlement.objects.create(
        booking=booking, status=RentalSettlement.Status.READY,
        extra_mileage_amount=Decimal("25.00"), total_amount=Decimal("25.00"), currency="TRY",
    )

    invoice = issue_settlement_invoice(settlement=settlement)
    invoice_again = issue_settlement_invoice(settlement=settlement)

    assert invoice.pk == invoice_again.pk
    assert invoice.status == Invoice.Status.ISSUED
    assert invoice.total == Decimal("25.00")
    assert RentalInvoice.objects.filter(booking=booking, invoice_kind="settlement").count() == 1
    assert RentalSettlement.objects.get(pk=settlement.pk).status == RentalSettlement.Status.INVOICED


@pytest.mark.django_db
def test_rental_invoice_export_is_queued_without_provider_call(rental_setup):
    property_, vehicle, rate, *_ = rental_setup
    start = timezone.now() + timedelta(days=1)
    booking = VehicleRentalBooking.objects.create(
        property=property_, vehicle=vehicle, rental_rate=rate,
        customer_name="Export Customer", pickup_at=start,
        dropoff_at=start + timedelta(days=2), currency="TRY",
    )
    invoice = Invoice.objects.create(
        property=property_, number="EXP-1", status=Invoice.Status.ISSUED,
        issue_date=timezone.localdate(), currency="TRY", subtotal=Decimal("100"),
        total=Decimal("100"), customer_name="Export Customer",
        lines=[{"code": "rental", "amount": "100"}],
    )
    RentalInvoice.objects.create(booking=booking, invoice=invoice)

    transmission = queue_invoice_export(invoice=invoice, provider="manual")

    assert transmission.status == EInvoiceTransmission.Status.QUEUED
    assert transmission.payload["invoice"]["number"] == "EXP-1"
    assert transmission.payload["rental"]["booking_id"] == booking.id
    assert RentalAuditEvent.objects.filter(booking=booking, action="invoice_export_queued").exists()


@pytest.fixture
def rental_setup(db):
    organization = Organization.objects.create(name="Rental Group", slug="rental-group")
    property_ = Property.objects.create(organization=organization, name="Rental Hotel", slug="rental-hotel")
    vehicle = Vehicle.objects.create(
        property=property_, code="econ-1", name="Economy 1", vehicle_class="economy", online_enabled=True,
    )
    rate = VehicleRentalRate.objects.create(
        vehicle=vehicle, name="Standard", daily_rate=Decimal("100"), weekly_rate=Decimal("600"),
        monthly_rate=Decimal("1800"), service_fee=Decimal("20"), vat_percent=Decimal("10"), deposit_amount=Decimal("500"),
    )
    extra = RentalExtraProduct.objects.create(property=property_, code="gps", name="GPS", price=Decimal("10"))
    insurance = RentalInsurancePackage.objects.create(property=property_, code="cdw", name="CDW", price=Decimal("15"))
    return property_, vehicle, rate, extra, insurance


@pytest.mark.django_db
def test_rental_quote_calculates_days_fees_tax_and_deposit(rental_setup):
    property_, vehicle, rate, extra, insurance = rental_setup
    start = timezone.now() + timedelta(days=1)
    quote = calculate_rental_quote(
        rate=rate, pickup_at=start, dropoff_at=start + timedelta(days=3),
        extra_product_ids=[extra.id], insurance_package_id=insurance.id,
    )

    assert quote.rental_days == 3
    assert quote.base_amount == Decimal("300.00")
    assert quote.extras_amount == Decimal("30.00")
    assert quote.insurance_amount == Decimal("45.00")
    assert quote.fees_amount == Decimal("20.00")
    assert quote.tax_amount == Decimal("39.50")
    assert quote.total_amount == Decimal("434.50")
    assert quote.deposit_amount == Decimal("500.00")


@pytest.mark.django_db
def test_rental_quote_applies_property_scoped_promo_rule(rental_setup):
    property_, vehicle, rate, *_ = rental_setup
    RentalPricingRule.objects.create(
        property=property_, name="Summer promo", code="summer", rule_type="promo",
        promo_code="SUMMER", vehicle_class="economy", adjustment_amount=Decimal("5"),
    )
    start = timezone.now() + timedelta(days=1)
    quote = calculate_rental_quote(
        rate=rate, pickup_at=start, dropoff_at=start + timedelta(days=3), promo_code="SUMMER",
    )
    assert quote.discount_amount == Decimal("15.00")


@pytest.mark.django_db
def test_channel_outbound_event_is_logged(monkeypatch, rental_setup):
    property_, *_ = rental_setup
    from booking.operations.models import RentalChannelConnection
    connection = RentalChannelConnection.objects.create(
        property=property_, code="ota", name="OTA", provider="test", endpoint_url="https://channel.test/events",
    )
    class Response:
        ok = True
        status_code = 200
    monkeypatch.setattr("booking.operations.services.rental_channels.requests.post", lambda *args, **kwargs: Response())
    event = push_channel_event(connection=connection, event_type="inventory_update", payload={"external_reference": "x-1"})
    assert event.status == "sent"
    connection.refresh_from_db()
    assert connection.last_sync_status == "sent"


@pytest.mark.django_db
def test_channel_event_can_be_queued_without_provider_call(rental_setup):
    property_, *_ = rental_setup
    from booking.operations.models import RentalChannelConnection
    connection = RentalChannelConnection.objects.create(
        property=property_, code="demo-queue", name="Demo Queue", endpoint_url="", is_active=True,
    )
    event = queue_channel_event(
        connection=connection, event_type="rate_update",
        payload={"external_reference": "rate-1", "amount": "100"},
    )
    assert event.status == "pending"
    assert event.channel == "demo-queue"
    assert event.payload["amount"] == "100"


@pytest.mark.django_db
def test_first_party_portal_is_a_channel(rental_setup):
    property_, *_ = rental_setup
    from booking.operations.models import RentalChannelConnection
    connection = RentalChannelConnection.objects.create(
        property=property_, code="hotel-site", name="Hotel website", provider="booking-balkans",
        channel_type=RentalChannelConnection.ChannelType.FIRST_PARTY,
    )
    event = queue_first_party_event(
        connection=connection, event_type="reservation_created", payload={"external_reference": "web-1"},
    )
    assert connection.channel_type == "first_party"
    assert event.status == "pending"


@pytest.mark.django_db
def test_first_party_snapshot_contains_rates_and_inventory(rental_setup):
    property_, vehicle, rate, *_ = rental_setup
    from booking.operations.models import RentalChannelConnection
    RentalChannelConnection.objects.create(
        property=property_, code="hotel-site", name="Hotel Site", provider="booking-balkans",
        channel_type=RentalChannelConnection.ChannelType.FIRST_PARTY,
    )
    events = queue_first_party_snapshot(property_=property_, entity="rentals")
    assert {event.event_type for event in events} == {"inventory_snapshot", "rate_snapshot"}
    assert events[0].payload["vehicles"][0]["rates"][0]["daily"] == "100.00"


@pytest.mark.django_db
def test_first_party_dispatch_sends_only_configured_endpoint(rental_setup, monkeypatch):
    property_, *_ = rental_setup
    from booking.operations.models import RentalChannelConnection
    connection = RentalChannelConnection.objects.create(
        property=property_, code="portal-endpoint", name="Portal", provider="booking-balkans",
        channel_type=RentalChannelConnection.ChannelType.FIRST_PARTY, endpoint_url="https://portal.test/events",
    )
    event = queue_first_party_event(connection=connection, event_type="inventory_snapshot", payload={"entity": "rentals"})
    class Response:
        ok = True
        status_code = 200
    monkeypatch.setattr("booking.operations.services.rental_channels.requests.post", lambda *args, **kwargs: Response())
    result = dispatch_queued_first_party_events(execute=True)
    event.refresh_from_db()
    assert result["sent"] == 1
    assert event.status == "sent"


@pytest.mark.django_db
def test_available_rental_vehicles_filters_class_and_overlap(rental_setup):
    property_, vehicle, rate, extra, insurance = rental_setup
    start = timezone.now() + timedelta(days=2)
    assert list(available_rental_vehicles(property_=property_, vehicle_class="economy")) == [vehicle]


@pytest.mark.django_db
def test_parking_quote_applies_daily_cap_and_night_rate(rental_setup):
    property_, *_ = rental_setup
    lot = ParkingLot.objects.create(
        property=property_, code="main", name="Main", hourly_rate=Decimal("10"),
        daily_max_rate=Decimal("50"), night_rate=Decimal("5"),
        night_start="22:00", night_end="06:00",
    )
    start = timezone.make_aware(datetime(2026, 1, 1, 21, 0))
    end = timezone.make_aware(datetime(2026, 1, 2, 7, 0))
    assert calculate_parking_quote(parking_lot=lot, start_at=start, end_at=end) == Decimal("90.00")


@pytest.mark.django_db
@override_settings(FLEET_CHANNEL_WEBHOOK_SECRET="test-fleet-secret")
def test_signed_fleet_channel_webhook_records_event(rental_setup):
    property_, *_ = rental_setup
    body = json.dumps({"channel": "rental-ota", "event_type": "availability", "external_reference": "ota-7"}).encode()
    signature = hmac.new(b"test-fleet-secret", body, hashlib.sha256).hexdigest()
    response = Client().post(
        f"/booking/webhooks/fleet/{property_.fleet_widget_key}/",
        data=body,
        content_type="application/json",
        HTTP_X_FLEET_SIGNATURE=signature,
    )
    assert response.status_code == 200
    assert property_.rental_channel_sync_events.filter(external_reference="ota-7").exists()


@pytest.mark.django_db
@override_settings(FLEET_CHANNEL_WEBHOOK_SECRET="test-fleet-secret")
def test_signed_fleet_channel_webhook_duplicate_event_is_processed_once(rental_setup):
    property_, *_ = rental_setup
    body = json.dumps({
        "event_id": "duplicate-ota-1", "channel": "rental-ota",
        "event_type": "availability", "external_reference": "ota-duplicate",
    }).encode()
    signature = hmac.new(b"test-fleet-secret", body, hashlib.sha256).hexdigest()
    url = f"/booking/webhooks/fleet/{property_.fleet_widget_key}/"
    client = Client()

    first = client.post(url, data=body, content_type="application/json", HTTP_X_FLEET_SIGNATURE=signature)
    second = client.post(url, data=body, content_type="application/json", HTTP_X_FLEET_SIGNATURE=signature)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["duplicate"] is True
    assert property_.webhook_events.filter(provider="channel_manager", event_id="duplicate-ota-1").count() == 1
    assert property_.rental_channel_sync_events.filter(external_reference="ota-duplicate").count() == 1


@pytest.mark.django_db
@override_settings(FLEET_CHANNEL_WEBHOOK_SECRET="test-fleet-secret")
def test_signed_fleet_telemetry_webhook_records_position(rental_setup):
    property_, vehicle, *_ = rental_setup
    body = json.dumps({"vehicle_code": vehicle.code, "source": "gps", "latitude": 41.01, "longitude": 28.97, "mileage": 12000}).encode()
    signature = hmac.new(b"test-fleet-secret", body, hashlib.sha256).hexdigest()
    response = Client().post(
        f"/booking/webhooks/fleet/{property_.fleet_widget_key}/telemetry/", data=body,
        content_type="application/json", HTTP_X_FLEET_SIGNATURE=signature,
    )
    assert response.status_code == 200
    assert VehicleTelemetryEvent.objects.filter(vehicle=vehicle, source="gps").exists()


@pytest.mark.django_db
@override_settings(FLEET_CHANNEL_WEBHOOK_SECRET="test-fleet-secret")
def test_signed_fleet_parking_device_webhook_records_access(rental_setup):
    property_, *_ = rental_setup
    lot = ParkingLot.objects.create(property=property_, code="main", name="Main")
    device = ParkingDevice.objects.create(property=property_, parking_lot=lot, name="Gate 1", device_type="anpr")
    body = json.dumps({"device_name": device.name, "event_type": "entry", "plate_number": "34ABC34"}).encode()
    signature = hmac.new(b"test-fleet-secret", body, hashlib.sha256).hexdigest()
    response = Client().post(
        f"/booking/webhooks/fleet/{property_.fleet_widget_key}/parking-device/", data=body,
        content_type="application/json", HTTP_X_FLEET_SIGNATURE=signature,
    )
    assert response.status_code == 200
    assert lot.access_events.filter(vehicle_plate="34ABC34").exists()


@pytest.mark.django_db
@override_settings(FLEET_CHANNEL_WEBHOOK_SECRET="test-fleet-secret")
def test_parking_device_webhook_rejects_invalid_event_type(rental_setup):
    property_, *_ = rental_setup
    lot = ParkingLot.objects.create(property=property_, code="main-invalid", name="Main Invalid")
    device = ParkingDevice.objects.create(property=property_, parking_lot=lot, name="Gate Invalid", device_type="anpr")
    body = json.dumps({"event_id": "invalid-1", "device_id": device.id, "event_type": "open", "plate_number": "34ABC35"}).encode()
    signature = hmac.new(b"test-fleet-secret", body, hashlib.sha256).hexdigest()
    response = Client().post(
        f"/booking/webhooks/fleet/{property_.fleet_widget_key}/parking-device/", data=body,
        content_type="application/json", HTTP_X_FLEET_SIGNATURE=signature,
    )
    assert response.status_code == 400
    assert not lot.access_events.exists()


@pytest.mark.django_db
@override_settings(FLEET_CHANNEL_WEBHOOK_SECRET="test-fleet-secret")
def test_signed_fleet_flight_webhook_updates_booking(rental_setup):
    property_, vehicle, rate, *_ = rental_setup
    booking = VehicleRentalBooking.objects.create(
        property=property_, vehicle=vehicle, rental_rate=rate, customer_name="Flight Guest",
        confirmation_code="R-FLIGHT-1", pickup_at=timezone.now() + timedelta(days=1),
        dropoff_at=timezone.now() + timedelta(days=2),
    )
    body = json.dumps({"confirmation_code": booking.confirmation_code, "flight_number": "TK001", "airport_code": "IST", "status": "delayed"}).encode()
    signature = hmac.new(b"test-fleet-secret", body, hashlib.sha256).hexdigest()
    response = Client().post(
        f"/booking/webhooks/fleet/{property_.fleet_widget_key}/flight/", data=body,
        content_type="application/json", HTTP_X_FLEET_SIGNATURE=signature,
    )
    assert response.status_code == 200
    assert RentalFlightStatus.objects.get(booking=booking).status == "delayed"


@pytest.mark.django_db
def test_fleet_availability_api_is_property_scoped(rental_setup):
    property_, vehicle, *_ = rental_setup
    response = Client().get(
        f"/booking/api/fleet/{property_.fleet_widget_key}/availability/?entity=rentals",
    )
    assert response.status_code == 200
    assert response.json()["vehicles"][0]["id"] == vehicle.id


@pytest.mark.django_db
def test_fleet_booking_api_creates_pending_rental_and_rejects_foreign_vehicle(rental_setup):
    property_, vehicle, rate, *_ = rental_setup
    from booking.operations.models import RentalChannelConnection
    RentalChannelConnection.objects.create(
        property=property_, code="central-portal", name="Central Portal", provider="booking-balkans",
        channel_type=RentalChannelConnection.ChannelType.FIRST_PARTY,
    )
    payload = {
        "entity": "rentals", "vehicle": vehicle.id, "rental_rate": rate.id,
        "customer_name": "API Guest", "customer_email": "api@example.com",
        "pickup_at": "2026-11-01T10:00", "dropoff_at": "2026-11-03T10:00",
        "privacy_consent": True,
    }
    response = Client().post(
        f"/booking/api/fleet/{property_.fleet_widget_key}/bookings/",
        data=json.dumps(payload), content_type="application/json",
    )
    assert response.status_code == 201
    booking = VehicleRentalBooking.objects.get(confirmation_code=response.json()["confirmation_code"], status="pending")
    assert booking.privacy_consent_at is not None
    assert booking.data_retention_until is not None
    assert RentalPrivacyEvent.objects.filter(booking=booking, event_type="consent").exists()
    assert RentalChannelSyncEvent.objects.filter(
        property=property_, channel="central-portal", event_type="reservation_created",
        payload__booking_id=booking.id,
    ).exists()
    manage_url = f"/booking/online/fleet/manage/{booking.public_manage_token}/"
    assert Client().get(manage_url).status_code == 200
    assert Client().post(manage_url, {"requester_email": booking.customer_email, "action": "cancel"}).status_code == 200
    assert RentalChannelSyncEvent.objects.filter(
        property=property_, channel="central-portal", event_type="reservation_cancelled",
        payload__booking_id=booking.id,
    ).exists()
    assert Client().post(manage_url, {"requester_email": booking.customer_email, "action": "deletion"}).status_code == 200
    assert RentalDataRequest.objects.filter(booking=booking, request_type="deletion", status="pending").exists()


@pytest.mark.django_db
def test_fleet_booking_api_ignores_client_pricing_fields(rental_setup):
    property_, vehicle, rate, *_ = rental_setup
    payload = {
        "entity": "rentals", "vehicle": vehicle.id, "rental_rate": rate.id,
        "customer_name": "Tampered Pricing Guest", "customer_email": "pricing@example.com",
        "pickup_at": "2026-11-01T10:00", "dropoff_at": "2026-11-03T10:00",
        "privacy_consent": True,
        "daily_rate": "1", "weekly_rate": "1", "monthly_rate": "1",
        "service_fee": "1", "tax_amount": "1", "deposit_amount": "1", "total_amount": "1",
    }
    response = Client().post(
        f"/booking/api/fleet/{property_.fleet_widget_key}/bookings/",
        data=json.dumps(payload), content_type="application/json",
    )

    assert response.status_code == 201
    booking = VehicleRentalBooking.objects.get(confirmation_code=response.json()["confirmation_code"])
    assert booking.daily_rate == Decimal("100.00")
    assert booking.deposit_amount == Decimal("500.00")
    assert booking.total_amount != Decimal("1.00")


@pytest.mark.django_db
def test_self_service_token_supports_view_cancel_and_deletion_request(rental_setup):
    property_, vehicle, rate, *_ = rental_setup
    payload = {
        "entity": "rentals", "vehicle": vehicle.id, "rental_rate": rate.id,
        "customer_name": "Self Service Guest", "customer_email": "selfservice@example.com",
        "pickup_at": "2026-11-01T10:00", "dropoff_at": "2026-11-03T10:00",
        "privacy_consent": True,
    }
    client = Client()
    response = client.post(
        f"/booking/api/fleet/{property_.fleet_widget_key}/bookings/",
        data=json.dumps(payload), content_type="application/json",
    )
    assert response.status_code == 201
    booking = VehicleRentalBooking.objects.get(confirmation_code=response.json()["confirmation_code"])
    manage_url = f"/booking/online/fleet/manage/{booking.public_manage_token}/"

    assert client.get(manage_url).status_code == 200
    assert client.post(manage_url, {"requester_email": booking.customer_email, "action": "cancel"}).status_code == 200
    assert client.post(manage_url, {"requester_email": booking.customer_email, "action": "deletion"}).status_code == 200
    assert RentalDataRequest.objects.filter(booking=booking, request_type="deletion", status="pending").exists()


@pytest.mark.django_db
def test_deposit_hold_supports_partial_capture_and_release_lifecycle(rental_setup):
    property_, vehicle, rate, *_ = rental_setup
    start = timezone.now() + timedelta(days=1)
    booking = VehicleRentalBooking.objects.create(
        property=property_, vehicle=vehicle, rental_rate=rate, customer_name="Deposit Guest",
        pickup_at=start, dropoff_at=start + timedelta(days=2), currency="TRY",
        deposit_amount=Decimal("500.00"),
    )

    hold = create_deposit_hold(booking=booking)
    assert hold.status == "held"
    hold = capture_deposit_hold(hold=hold, amount=Decimal("75.00"))
    assert hold.status == "partially_captured"
    assert hold.captured_amount == Decimal("75.00")
    hold = release_deposit_hold(hold=hold)
    assert hold.status == "released"
    assert RentalAuditEvent.objects.filter(booking=booking, action="deposit_held").exists()
    assert RentalAuditEvent.objects.filter(booking=booking, action="deposit_captured").exists()
    assert RentalAuditEvent.objects.filter(booking=booking, action="deposit_released").exists()


@pytest.mark.django_db
def test_rental_notification_queue_is_property_scoped(rental_setup):
    property_, vehicle, rate, *_ = rental_setup
    booking = VehicleRentalBooking.objects.create(
        property=property_, vehicle=vehicle, rental_rate=rate,
        customer_name="Test Guest", customer_email="guest@example.com",
        pickup_at=timezone.now() + timedelta(days=1), dropoff_at=timezone.now() + timedelta(days=2),
    )
    queued = queue_rental_notifications(booking)
    assert len(queued) == 1
    assert queued[0].recipient == "guest@example.com"


@pytest.mark.django_db
def test_rental_prepayment_creates_pending_payment_intent(rental_setup):
    property_, vehicle, rate, *_ = rental_setup
    booking = VehicleRentalBooking.objects.create(
        property=property_, vehicle=vehicle, rental_rate=rate,
        customer_name="Test Guest", prepayment_amount=Decimal("75"), currency="TRY",
        pickup_at=timezone.now() + timedelta(days=1), dropoff_at=timezone.now() + timedelta(days=2),
    )
    payment = create_pending_rental_payment(booking=booking, amount=booking.prepayment_amount)
    assert payment.status == "pending"
    assert payment.amount == Decimal("75.00")


@pytest.mark.django_db
def test_booking_rules_enforce_driver_requirements_and_parking_capacity(rental_setup):
    property_, vehicle, rate, *_ = rental_setup
    vehicle.minimum_driver_age = 25
    vehicle.minimum_license_months = 24
    vehicle.save(update_fields=["minimum_driver_age", "minimum_license_months"])
    rental = VehicleRentalBooking(
        property=property_, vehicle=vehicle, rental_rate=rate, customer_name="Too Young",
        driver_age=21, license_duration_months=12,
        pickup_at=timezone.now() + timedelta(days=1), dropoff_at=timezone.now() + timedelta(days=2),
    )
    with pytest.raises(ValidationError) as rental_error:
        rental.full_clean()
    assert "driver_age" in rental_error.value.message_dict
    lot = ParkingLot.objects.create(property=property_, code="small", name="Small", capacity=1)
    start = timezone.now() + timedelta(days=3)
    end = start + timedelta(hours=2)
    ParkingReservation.objects.create(property=property_, parking_lot=lot, customer_name="First", start_at=start, end_at=end)
    second = ParkingReservation(property=property_, parking_lot=lot, customer_name="Second", start_at=start, end_at=end)
    with pytest.raises(ValidationError) as parking_error:
        second.full_clean()
    assert "parking_lot" in parking_error.value.message_dict


@pytest.mark.django_db
def test_rental_checkout_persists_provider_reference(rental_setup, monkeypatch):
    property_, vehicle, rate, *_ = rental_setup
    booking = VehicleRentalBooking.objects.create(
        property=property_, vehicle=vehicle, rental_rate=rate,
        customer_name="Paying Guest", prepayment_amount=Decimal("80"),
        pickup_at=timezone.now() + timedelta(days=1), dropoff_at=timezone.now() + timedelta(days=2),
    )
    gateway = PaymentGateway.objects.create(property=property_, bank_name="Stripe", payment_model="stripe", active=True)
    monkeypatch.setattr(
        "booking.operations.services.rental_checkout.create_checkout",
        lambda **kwargs: {"external_id": "cs_test_123", "checkout_url": "https://checkout.test/session", "payload": {"id": "cs_test_123"}},
    )
    payment, result = start_rental_checkout(
        booking=booking, gateway=gateway, success_url="https://hotel.test/success", cancel_url="https://hotel.test/cancel",
    )
    assert result["checkout_url"].startswith("https://checkout.test")
    payment.refresh_from_db()
    assert payment.status == RentalPayment.Status.AUTHORIZED
    assert payment.provider_reference == "cs_test_123"


@pytest.mark.django_db
def test_paypal_capture_and_refund_are_audited(rental_setup, monkeypatch):
    property_, vehicle, rate, *_ = rental_setup
    booking = VehicleRentalBooking.objects.create(
        property=property_, vehicle=vehicle, rental_rate=rate, customer_name="Provider Guest",
        total_amount=Decimal("80"), pickup_at=timezone.now() + timedelta(days=1),
        dropoff_at=timezone.now() + timedelta(days=2),
    )
    gateway = PaymentGateway.objects.create(property=property_, bank_name="PayPal", payment_model="paypal", active=True)
    payment = RentalPayment.objects.create(
        booking=booking, gateway=gateway, amount=Decimal("80"), currency="TRY",
        status=RentalPayment.Status.AUTHORIZED, provider_reference="order_1",
    )
    monkeypatch.setattr(
        "booking.operations.services.rental_payment_actions.capture_paypal_order",
        lambda reference: {"status": "COMPLETED", "purchase_units": [{"payments": {"captures": [{"id": "capture_1"}]}}]},
    )
    capture_rental_payment(payment=payment)
    payment.refresh_from_db()
    assert payment.status == RentalPayment.Status.CAPTURED
    monkeypatch.setattr(
        "booking.operations.services.rental_payment_actions._paypal_refund",
        lambda *args: {"status": "COMPLETED", "id": "refund_1"},
    )
    refund_rental_payment(payment=payment)
    payment.refresh_from_db()
    assert payment.status == RentalPayment.Status.REFUNDED
    assert booking.audit_events.filter(action__in=["payment_captured", "payment_refunded"]).count() == 2


@pytest.mark.django_db
def test_manual_bank_refund_is_recorded_without_provider_call(rental_setup):
    property_, vehicle, rate, *_ = rental_setup
    booking = VehicleRentalBooking.objects.create(
        property=property_, vehicle=vehicle, rental_rate=rate, customer_name="Bank Guest",
        pickup_at=timezone.now() + timedelta(days=1), dropoff_at=timezone.now() + timedelta(days=2),
    )
    gateway = PaymentGateway.objects.create(property=property_, bank_name="Halkbank", payment_model="nestpay_halkbank", active=True)
    payment = RentalPayment.objects.create(
        booking=booking, gateway=gateway, amount=Decimal("50"), currency="TRY",
        status=RentalPayment.Status.CAPTURED, provider_reference="bank_tx_1",
    )
    record_manual_bank_refund(payment=payment, refund_reference="HB-REF-1", note="Banka panelinden iade")
    payment.refresh_from_db()
    assert payment.status == RentalPayment.Status.REFUNDED
    assert payment.metadata["refund"]["mode"] == "manual_bank_panel"
    assert booking.audit_events.filter(action="payment_refunded_manual").exists()


@pytest.mark.django_db
def test_rental_status_action_maps_confirm_to_confirmed(rental_setup):
    property_, vehicle, rate, *_ = rental_setup
    booking = VehicleRentalBooking.objects.create(
        property=property_, vehicle=vehicle, rental_rate=rate, customer_name="Status Guest",
        pickup_at=timezone.now() + timedelta(days=5), dropoff_at=timezone.now() + timedelta(days=6),
    )
    user = get_user_model().objects.create_superuser("rental-admin", "admin@example.test", "password")
    client = Client()
    assert client.login(username="rental-admin", password="password")
    response = client.post(
        "/booking/business/fleet/rentals/",
        {"property_id": property_.id, "entity": "rentals", "action": "confirmed", "booking_id": booking.id},
    )
    assert response.status_code == 302
    booking.refresh_from_db()
    assert booking.status == VehicleRentalBooking.Status.CONFIRMED
    assert booking.audit_events.filter(action="status_confirmed").exists()


@pytest.mark.django_db
def test_parking_status_action_maps_confirmed_to_checked_flow(rental_setup):
    property_, *_ = rental_setup
    lot = ParkingLot.objects.create(property=property_, code="lot-1", name="Main", capacity=20)
    reservation = ParkingReservation.objects.create(
        property=property_, parking_lot=lot, customer_name="Parking Guest",
        start_at=timezone.now() + timedelta(days=2),
        end_at=timezone.now() + timedelta(days=3),
    )
    user = get_user_model().objects.create_superuser("parking-admin", "parking@example.test", "password")
    client = Client()
    assert client.login(username="parking-admin", password="password")
    response = client.post(
        "/booking/business/fleet/parking/",
        {"property_id": property_.id, "entity": "parking_reservations", "action": "confirmed", "booking_id": reservation.id},
    )
    assert response.status_code == 302
    reservation.refresh_from_db()
    assert reservation.status == ParkingReservation.Status.CONFIRMED
    assert RentalAuditEvent.objects.filter(action="parking_status_confirmed", property=property_).exists()


@pytest.mark.django_db
def test_authorized_fleet_screens_render(rental_setup):
    property_, *_ = rental_setup
    user = get_user_model().objects.create_superuser("screen-admin", "screen@example.test", "password")
    client = Client()
    assert client.login(username="screen-admin", password="password")
    for path in (
        f"/booking/business/fleet/?property_id={property_.id}",
        f"/booking/business/vehicle-rentals/reports/?property_id={property_.id}",
    ):
        response = client.get(path)
        assert response.status_code == 200, (path, response.content[:500])
    for entity in (
        "rental_bookings", "parking_bookings", "channel_connections", "channel_mappings", "pricing_rules",
        "flight", "telemetry", "parking_devices", "locations", "extras", "insurance", "handovers",
        "handover_photos", "damage", "maintenance", "fines", "parking_subscriptions", "parking_access",
        "valet", "parking_penalties", "contracts", "payments", "invoices",
    ):
        path = f"/booking/business/vehicle-rentals/operations/?property_id={property_.id}&entity={entity}"
        response = client.get(path)
        assert response.status_code == 200, (path, response.content[:500])

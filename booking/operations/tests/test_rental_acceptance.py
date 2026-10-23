from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.forms import ModelChoiceField, ModelMultipleChoiceField
from django.test import Client
from django.utils import timezone

from booking.operations.models import (
    AccessPermission,
    ParkingLot,
    ParkingReservation,
    ParkingSpace,
    PropertyRole,
    RentalAuditEvent,
    UserPropertyAccess,
    VehicleRentalBooking,
    VehicleRentalRate,
)
from booking.tenancy.models import Membership, MembershipRole, Organization, Property, Vehicle


@pytest.fixture
def acceptance_setup(db):
    user_model = get_user_model()
    organization = Organization.objects.create(name="Acceptance Group", slug="acceptance-group")
    property_a = Property.objects.create(organization=organization, name="Demo Hotel A", slug="demo-hotel-a")
    property_b = Property.objects.create(organization=organization, name="Demo Hotel B", slug="demo-hotel-b")

    manage_permission = AccessPermission.objects.get_or_create(
        code="operations.front_office.manage",
        defaults={
            "name": "Vehicle and parking operations",
            "module": "vehicle_rental",
            "action": "manage",
            "is_active": True,
        },
    )[0]
    manager_role_a = PropertyRole.objects.create(property=property_a, name="Property Manager")
    manager_role_a.permissions.add(manage_permission)
    manager_role_b = PropertyRole.objects.create(property=property_b, name="Property Manager")
    manager_role_b.permissions.add(manage_permission)
    readonly_role_a = PropertyRole.objects.create(property=property_a, name="Operations Read-only")

    manager_a = user_model.objects.create_user("acceptance-manager-a", password="password")
    manager_b = user_model.objects.create_user("acceptance-manager-b", password="password")
    readonly_a = user_model.objects.create_user("acceptance-readonly-a", password="password")
    for user, property_, role in (
        (manager_a, property_a, manager_role_a),
        (manager_b, property_b, manager_role_b),
        (readonly_a, property_a, readonly_role_a),
    ):
        Membership.objects.create(
            organization=organization, user=user, property=property_, role=MembershipRole.MANAGER,
        )
        UserPropertyAccess.objects.create(user=user, property=property_, role=role)

    vehicle_a = Vehicle.objects.create(
        property=property_a, code="accept-a", name="Acceptance Vehicle A", vehicle_class="economy",
        online_enabled=True,
    )
    vehicle_b = Vehicle.objects.create(
        property=property_b, code="accept-b", name="Acceptance Vehicle B", vehicle_class="economy",
        online_enabled=True,
    )
    rate_a = VehicleRentalRate.objects.create(
        vehicle=vehicle_a, name="Acceptance Rate A", daily_rate=Decimal("100"), deposit_amount=Decimal("500"),
    )
    rate_b = VehicleRentalRate.objects.create(
        vehicle=vehicle_b, name="Acceptance Rate B", daily_rate=Decimal("100"), deposit_amount=Decimal("500"),
    )
    lot_a = ParkingLot.objects.create(property=property_a, code="accept-a", name="Acceptance Parking A", capacity=2)
    lot_b = ParkingLot.objects.create(property=property_b, code="accept-b", name="Acceptance Parking B", capacity=2)
    space_a = ParkingSpace.objects.create(parking_lot=lot_a, code="A-01")
    space_b = ParkingSpace.objects.create(parking_lot=lot_b, code="B-01")
    start = timezone.now() + timedelta(days=2)

    return {
        "organization": organization,
        "property_a": property_a,
        "property_b": property_b,
        "manager_a": manager_a,
        "manager_b": manager_b,
        "readonly_a": readonly_a,
        "vehicle_a": vehicle_a,
        "vehicle_b": vehicle_b,
        "rate_a": rate_a,
        "rate_b": rate_b,
        "lot_a": lot_a,
        "lot_b": lot_b,
        "space_a": space_a,
        "space_b": space_b,
        "start": start,
    }


@pytest.mark.django_db
def test_vehicle_and_parking_records_support_database_crud(acceptance_setup):
    data = acceptance_setup
    start = data["start"]

    rental = VehicleRentalBooking.objects.create(
        property=data["property_a"], vehicle=data["vehicle_a"], rental_rate=data["rate_a"],
        customer_name="CRUD Rental", pickup_at=start, dropoff_at=start + timedelta(days=2),
        daily_rate=Decimal("100"), total_amount=Decimal("200"), deposit_amount=Decimal("500"),
        created_by=data["manager_a"],
    )
    assert VehicleRentalBooking.objects.get(pk=rental.pk).customer_name == "CRUD Rental"
    rental.customer_name = "CRUD Rental Updated"
    rental.save(update_fields=["customer_name", "updated_at"])
    assert VehicleRentalBooking.objects.get(pk=rental.pk).customer_name == "CRUD Rental Updated"
    rental.delete()
    assert not VehicleRentalBooking.objects.filter(pk=rental.pk).exists()

    parking = ParkingReservation.objects.create(
        property=data["property_a"], parking_lot=data["lot_a"], parking_space=data["space_a"],
        customer_name="CRUD Parking", start_at=start, end_at=start + timedelta(hours=3),
        created_by=data["manager_a"],
    )
    assert ParkingReservation.objects.get(pk=parking.pk).customer_name == "CRUD Parking"
    parking.customer_name = "CRUD Parking Updated"
    parking.save(update_fields=["customer_name", "updated_at"])
    assert ParkingReservation.objects.get(pk=parking.pk).customer_name == "CRUD Parking Updated"
    parking.delete()
    assert not ParkingReservation.objects.filter(pk=parking.pk).exists()


@pytest.mark.django_db
def test_rental_bookings_operation_form_create_update_and_audit(acceptance_setup):
    data = acceptance_setup
    start = data["start"]
    client = Client()
    assert client.login(username="acceptance-manager-a", password="password")
    url = "/booking/business/vehicle-rentals/operations/"
    payload = {
        "property_id": data["property_a"].id,
        "entity": "rental_bookings",
        "vehicle": data["vehicle_a"].id,
        "rental_rate": data["rate_a"].id,
        "customer_name": "Operation Form Customer",
        "pickup_at": start.strftime("%Y-%m-%dT%H:%M"),
        "dropoff_at": (start + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M"),
        "status": VehicleRentalBooking.Status.PENDING,
        "source": "direct",
        "daily_rate": "100",
        "total_amount": "200",
        "deposit_amount": "500",
        "currency": "TRY",
        "additional_driver_count": "0",
        "locale": "tr-TR",
        "prepayment_amount": "0",
    }
    create_response = client.post(url, payload)
    assert create_response.status_code == 302
    booking = VehicleRentalBooking.objects.get(customer_name="Operation Form Customer")

    from booking.operations.forms import VehicleRentalBookingForm

    form = VehicleRentalBookingForm(instance=booking, property_=data["property_a"])
    update_payload = {}
    for name, field in form.fields.items():
        value = form.initial.get(name, "")
        if isinstance(field, (ModelChoiceField, ModelMultipleChoiceField)):
            if hasattr(value, "pk"):
                value = value.pk
            elif isinstance(value, (list, tuple)):
                value = [item.pk if hasattr(item, "pk") else item for item in value]
        elif hasattr(value, "strftime"):
            value = value.strftime("%Y-%m-%dT%H:%M") if hasattr(value, "hour") else value.strftime("%Y-%m-%d")
        update_payload[name] = "" if value is None else value
    update_payload.update({
        "action": "save",
        "customer_name": "Operation Form Customer Updated",
    })
    update_response = client.post(
        f"/booking/business/vehicle-rentals/{booking.pk}/?property_id={data['property_a'].id}",
        update_payload,
    )
    assert update_response.status_code == 302
    booking.refresh_from_db()
    assert booking.customer_name == "Operation Form Customer Updated"
    assert RentalAuditEvent.objects.filter(
        booking=booking, action="booking_updated", actor=data["manager_a"],
    ).exists()


@pytest.mark.django_db
def test_property_manager_cannot_read_or_mutate_other_property_records(acceptance_setup):
    data = acceptance_setup
    start = data["start"]
    rental_b = VehicleRentalBooking.objects.create(
        property=data["property_b"], vehicle=data["vehicle_b"], rental_rate=data["rate_b"],
        customer_name="Property B Secret", pickup_at=start, dropoff_at=start + timedelta(days=2),
        daily_rate=Decimal("100"), total_amount=Decimal("200"), deposit_amount=Decimal("500"),
        created_by=data["manager_b"],
    )
    client = Client()
    assert client.login(username="acceptance-manager-a", password="password")

    list_response = client.get(
        "/booking/business/vehicle-rentals/operations/",
        {"property_id": data["property_a"].id, "entity": "rental_bookings"},
    )
    assert list_response.status_code == 200
    assert b"Property B Secret" not in list_response.content

    detail_response = client.get(
        f"/booking/business/vehicle-rentals/{rental_b.pk}/",
        {"property_id": data["property_b"].id},
    )
    assert detail_response.status_code in {403, 404}

    before = VehicleRentalBooking.objects.get(pk=rental_b.pk).customer_name
    cross_property_post = client.post(
        f"/booking/business/vehicle-rentals/operations/?property_id={data['property_b'].id}",
        {"entity": "rental_bookings", "edit_id": rental_b.pk, "customer_name": "Hacked"},
    )
    assert cross_property_post.status_code in {403, 404}
    assert VehicleRentalBooking.objects.get(pk=rental_b.pk).customer_name == before


@pytest.mark.django_db
def test_parking_manager_cannot_read_or_mutate_other_property_records(acceptance_setup):
    data = acceptance_setup
    start = data["start"]
    parking_b = ParkingReservation.objects.create(
        property=data["property_b"], parking_lot=data["lot_b"], parking_space=data["space_b"],
        customer_name="Property B Parking Secret", start_at=start, end_at=start + timedelta(hours=3),
        created_by=data["manager_b"],
    )
    client = Client()
    assert client.login(username="acceptance-manager-a", password="password")

    list_response = client.get(
        "/booking/business/vehicle-rentals/operations/",
        {"property_id": data["property_a"].id, "entity": "parking_bookings"},
    )
    assert list_response.status_code == 200
    assert b"Property B Parking Secret" not in list_response.content

    edit_response = client.get(
        "/booking/business/vehicle-rentals/operations/",
        {"property_id": data["property_b"].id, "entity": "parking_bookings", "edit_id": parking_b.pk},
    )
    assert edit_response.status_code in {403, 404}

    before = ParkingReservation.objects.get(pk=parking_b.pk).customer_name
    cross_property_post = client.post(
        "/booking/business/vehicle-rentals/operations/",
        {"property_id": data["property_b"].id, "entity": "parking_bookings", "edit_id": parking_b.pk, "customer_name": "Hacked"},
    )
    assert cross_property_post.status_code in {403, 404}
    assert ParkingReservation.objects.get(pk=parking_b.pk).customer_name == before


@pytest.mark.django_db
def test_readonly_property_role_can_read_own_operations(acceptance_setup):
    data = acceptance_setup
    start = data["start"]
    VehicleRentalBooking.objects.create(
        property=data["property_a"], vehicle=data["vehicle_a"], rental_rate=data["rate_a"],
        customer_name="Read-only Visible Booking", pickup_at=start, dropoff_at=start + timedelta(days=2),
        daily_rate=Decimal("100"), total_amount=Decimal("200"), deposit_amount=Decimal("500"),
    )
    client = Client()
    assert client.login(username="acceptance-readonly-a", password="password")
    url = "/booking/business/vehicle-rentals/operations/"
    read_response = client.get(url, {"property_id": data["property_a"].id, "entity": "rental_bookings"})
    assert read_response.status_code == 200
    assert b"Read-only Visible Booking" in read_response.content


@pytest.mark.django_db
def test_readonly_property_role_cannot_mutate_vehicle_parking_operations(acceptance_setup):
    data = acceptance_setup
    start = data["start"]
    own_booking = VehicleRentalBooking.objects.create(
        property=data["property_a"], vehicle=data["vehicle_a"], rental_rate=data["rate_a"],
        customer_name="Read-only Mutation Target", pickup_at=start, dropoff_at=start + timedelta(days=2),
        daily_rate=Decimal("100"), total_amount=Decimal("200"), deposit_amount=Decimal("500"),
    )
    client = Client()
    assert client.login(username="acceptance-readonly-a", password="password")
    url = "/booking/business/vehicle-rentals/operations/"
    assert client.post(
        url,
        {"property_id": data["property_a"].id, "entity": "parking_bookings", "customer_name": "Denied"},
    ).status_code == 403
    assert client.post(
        url,
        {"property_id": data["property_a"].id, "entity": "rental_bookings", "edit_id": own_booking.pk, "customer_name": "Denied Update"},
    ).status_code == 403
    assert client.post(
        "/booking/business/fleet/rentals/",
        {"property_id": data["property_a"].id, "entity": "rentals", "booking_id": own_booking.pk, "action": "cancelled"},
    ).status_code == 403


@pytest.mark.django_db
def test_rental_booking_cancel_action_is_delete_equivalent_and_audited(acceptance_setup):
    data = acceptance_setup
    start = data["start"]
    booking = VehicleRentalBooking.objects.create(
        property=data["property_a"], vehicle=data["vehicle_a"], rental_rate=data["rate_a"],
        customer_name="Cancellation Candidate", pickup_at=start, dropoff_at=start + timedelta(days=2),
        daily_rate=Decimal("100"), total_amount=Decimal("200"), deposit_amount=Decimal("500"),
        created_by=data["manager_a"],
    )
    client = Client()
    assert client.login(username="acceptance-manager-a", password="password")
    response = client.post(
        "/booking/business/fleet/rentals/",
        {"property_id": data["property_a"].id, "entity": "rentals", "booking_id": booking.pk, "action": "cancelled"},
    )
    assert response.status_code == 302
    booking.refresh_from_db()
    assert booking.status == VehicleRentalBooking.Status.CANCELLED
    assert RentalAuditEvent.objects.filter(
        booking=booking, action="status_cancelled", actor=data["manager_a"],
    ).exists()

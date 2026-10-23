import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from booking.tenancy.models import Membership, Organization, Property
from booking.operations.models import RentalLocation


@pytest.mark.django_db
def test_property_member_can_render_hotel_dashboard():
    organization = Organization.objects.create(name="Hotel Group", slug="hotel-group")
    property_ = Property.objects.create(organization=organization, name="Main Hotel", slug="main-hotel")
    user = get_user_model().objects.create_user(username="tesis_admin", password="secret")
    Membership.objects.create(
        organization=organization,
        property=property_,
        user=user,
        role="manager",
        is_active=True,
    )

    client = Client()
    client.force_login(user)
    response = client.get("/booking/business/dashboard/")

    assert response.status_code == 200
    assert "Hotel Dashboard" in response.content.decode()


@pytest.mark.django_db
def test_property_member_cannot_see_other_property_operation_rows():
    organization = Organization.objects.create(name="Scoped Group", slug="scoped-group")
    allowed = Property.objects.create(organization=organization, name="Allowed Hotel", slug="allowed-hotel")
    hidden = Property.objects.create(organization=organization, name="Hidden Hotel", slug="hidden-hotel")
    RentalLocation.objects.create(property=allowed, code="ALLOWED", name="Allowed location", kind="branch")
    RentalLocation.objects.create(property=hidden, code="HIDDEN", name="Hidden location", kind="branch")
    user = get_user_model().objects.create_user(username="scoped_admin", password="secret")
    Membership.objects.create(organization=organization, property=allowed, user=user, role="manager", is_active=True)

    client = Client()
    client.force_login(user)
    response = client.get(
        "/booking/business/vehicle-rentals/operations/",
        {"property_id": allowed.id, "entity": "locations"},
    )

    assert response.status_code == 200
    body = response.content.decode()
    assert "Allowed location" in body
    assert "Hidden location" not in body

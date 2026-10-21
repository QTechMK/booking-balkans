import pytest
from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.test import RequestFactory

from booking.operations.middleware import RequiredPropertyMFAMiddleware
from booking.operations.models import PropertyRole, UserPropertyAccess
from booking.tenancy.models import Organization, Property


@pytest.fixture
def mfa_access_setup():
    organization = Organization.objects.create(name="Hotel Group", slug="hotel-group")
    property_ = Property.objects.create(organization=organization, name="Main Hotel", slug="main-hotel")
    role = PropertyRole.objects.create(property=property_, name="Manager")
    user = get_user_model().objects.create_user(username="manager", password="secret")
    UserPropertyAccess.objects.create(user=user, property=property_, role=role, two_factor_required=True)
    return user, property_


@pytest.mark.django_db
def test_required_property_mfa_redirects_to_mfa_setup(mfa_access_setup, monkeypatch):
    user, property_ = mfa_access_setup
    monkeypatch.setattr("booking.operations.middleware.is_mfa_enabled", lambda user: False)
    request = RequestFactory().get(f"/booking/business/dashboard/?property_id={property_.id}")
    request.user = user
    response = RequiredPropertyMFAMiddleware(lambda request: HttpResponse("ok"))(request)
    assert response.status_code == 302
    assert "/accounts/2fa/" in response["Location"]
    assert "next=" in response["Location"]


@pytest.mark.django_db
def test_required_property_mfa_allows_configured_user(mfa_access_setup, monkeypatch):
    user, property_ = mfa_access_setup
    monkeypatch.setattr("booking.operations.middleware.is_mfa_enabled", lambda user: True)
    request = RequestFactory().get(f"/booking/business/dashboard/?property_id={property_.id}")
    request.user = user
    response = RequiredPropertyMFAMiddleware(lambda request: HttpResponse("ok"))(request)
    assert response.status_code == 200
    assert response.content == b"ok"


@pytest.mark.django_db
def test_invalid_property_id_does_not_crash(mfa_access_setup, monkeypatch):
    user, _ = mfa_access_setup
    monkeypatch.setattr("booking.operations.middleware.is_mfa_enabled", lambda user: True)
    request = RequestFactory().get("/booking/business/dashboard/?property_id=invalid")
    request.user = user
    response = RequiredPropertyMFAMiddleware(lambda request: HttpResponse("ok"))(request)
    assert response.status_code == 200

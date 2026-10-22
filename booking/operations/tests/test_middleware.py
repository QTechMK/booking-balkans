from datetime import date, datetime, time

import pytest
from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.test import RequestFactory

from booking.operations.middleware import RequiredPropertyMFAMiddleware
from booking.operations.models import PropertyRole, UserAccessLog, UserPropertyAccess
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


@pytest.mark.django_db
def test_access_time_policy_allows_request_inside_window(mfa_access_setup, monkeypatch):
    user, property_ = mfa_access_setup
    access = UserPropertyAccess.objects.get(user=user, property=property_)
    access.two_factor_required = False
    access.allowed_from_time = time(9, 0)
    access.allowed_until_time = time(17, 0)
    access.save()
    monkeypatch.setattr("booking.operations.middleware.timezone.localdate", lambda: date(2026, 1, 1))
    monkeypatch.setattr("booking.operations.middleware.timezone.localtime", lambda *args, **kwargs: datetime(2026, 1, 1, 12, 0))
    request = RequestFactory().get(f"/booking/business/dashboard/?property_id={property_.id}")
    request.user = user
    response = RequiredPropertyMFAMiddleware(lambda request: HttpResponse("ok"))(request)
    assert response.status_code == 200


@pytest.mark.django_db
def test_access_time_policy_blocks_request_outside_window(mfa_access_setup, monkeypatch):
    user, property_ = mfa_access_setup
    access = UserPropertyAccess.objects.get(user=user, property=property_)
    access.two_factor_required = False
    access.allowed_from_time = time(9, 0)
    access.allowed_until_time = time(17, 0)
    access.save()
    monkeypatch.setattr("booking.operations.middleware.timezone.localdate", lambda: date(2026, 1, 1))
    monkeypatch.setattr("booking.operations.middleware.timezone.localtime", lambda *args, **kwargs: datetime(2026, 1, 1, 20, 0))
    request = RequestFactory().get(f"/booking/business/dashboard/?property_id={property_.id}")
    request.user = user
    response = RequiredPropertyMFAMiddleware(lambda request: HttpResponse("ok"))(request)
    assert response.status_code == 403
    assert UserAccessLog.objects.filter(user=user, property=property_, event="time_policy_denied").exists()

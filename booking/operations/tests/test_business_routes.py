import pytest
from django.test import Client


BUSINESS_ROUTES = (
    "/booking/business/dashboard/",
    "/booking/business/reports/",
    "/booking/business/property-settings/",
    "/booking/business/hotel-dictionaries/",
    "/booking/business/room-master/",
    "/booking/business/room-rack/",
    "/booking/business/housekeeping/",
    "/booking/business/maintenance/",
    "/booking/business/tasks/",
    "/booking/business/online-settings/",
    "/booking/business/crm/guests/",
    "/booking/business/crm/marketing/",
    "/booking/business/access/",
)


@pytest.mark.django_db
@pytest.mark.parametrize("route", BUSINESS_ROUTES)
def test_business_route_is_registered_and_protected(route):
    response = Client().get(route)

    assert response.status_code == 302, response.content[:500]
    assert "/accounts/login/" in response["Location"]

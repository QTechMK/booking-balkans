import pytest
from django.test import Client


BUSINESS_ROUTES = (
    "/booking/business/dashboard/",
    "/booking/business/reports/",
    "/booking/business/property-settings/",
    "/booking/business/hotel-dictionaries/",
    "/booking/business/room-master/",
    "/booking/business/fleet/",
    "/booking/business/fleet/parking/",
    "/booking/business/fleet/rentals/",
    "/booking/business/vehicle-rentals/operations/",
    "/booking/business/vehicle-rentals/reports/",
    "/booking/business/room-rack/",
    "/booking/business/housekeeping/",
    "/booking/business/maintenance/",
    "/booking/business/tasks/",
    "/booking/business/online-settings/",
    "/booking/business/crm/guests/",
    "/booking/business/crm/marketing/",
    "/booking/business/access/",
    "/booking/business/support/",
    "/booking/business/support/faq/",
    "/booking/business/support/education/",
    "/booking/business/support/referral/",
    "/booking/business/support/video/",
    "/booking/business/front-office/",
    "/booking/business/front-office/calls/",
    "/booking/business/accounting-definitions/",
    "/booking/business/invoices/",
    "/booking/business/payment-gateways/",
    "/booking/business/night-audit/",
    "/booking/business/agencies/",
)

RENTAL_OPERATION_ENTITIES = (
    "rental_bookings", "parking_bookings", "parking_map", "channel_connections", "channel_mappings",
    "pricing_rules", "flight", "telemetry", "parking_devices", "locations", "extras",
    "insurance", "handovers", "handover_photos", "damage", "maintenance", "fines",
    "parking_subscriptions", "parking_access", "valet", "parking_penalties", "contracts",
    "payments", "invoices", "driver_profiles", "cancellation_policies", "tax_rules", "privacy_requests",
)


@pytest.mark.django_db
@pytest.mark.parametrize("route", BUSINESS_ROUTES)
def test_business_route_is_registered_and_protected(route):
    response = Client().get(route)

    assert response.status_code == 302, response.content[:500]
    assert "/accounts/login/" in response["Location"]


@pytest.mark.django_db
@pytest.mark.parametrize("entity", RENTAL_OPERATION_ENTITIES)
def test_rental_operation_entity_is_registered_and_protected(entity):
    response = Client().get(f"/booking/business/vehicle-rentals/operations/?entity={entity}")

    assert response.status_code == 302, response.content[:500]
    assert "/accounts/login/" in response["Location"]

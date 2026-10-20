from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

from booking.tenancy.models import DailyRate, Inventory, Organization, Property, RatePlan, UnitType


@pytest.fixture
def availability_setup():
    organization = Organization.objects.create(name="Balkans", slug="balkans-api")
    property_ = Property.objects.create(
        organization=organization,
        name="API Hotel",
        slug="api-hotel",
    )
    unit_type = UnitType.objects.create(
        property=property_,
        name="Standard Room",
        code="standard-room-api",
    )
    rate_plan = RatePlan.objects.create(
        property=property_,
        unit_type=unit_type,
        name="Flexible",
        code="flexible-api",
    )
    for day in (date(2026, 11, 1), date(2026, 11, 2)):
        Inventory.objects.create(
            property=property_,
            unit_type=unit_type,
            date=day,
            total_capacity=3,
            blocked_capacity=1,
        )
        DailyRate.objects.create(
            rate_plan=rate_plan,
            date=day,
            amount=Decimal("1500.00"),
        )
    return property_, rate_plan


@pytest.mark.django_db
def test_availability_api_returns_priced_days(client, availability_setup):
    property_, rate_plan = availability_setup

    response = client.get(
        reverse("tenancy:availability", kwargs={"property_id": property_.id}),
        {
            "rate_plan": rate_plan.id,
            "check_in": "2026-11-01",
            "check_out": "2026-11-03",
            "quantity": 1,
        },
    )

    assert response.status_code == 200
    assert response.json()["available"] is True
    assert response.json()["total_amount"] == "3000.00"
    assert len(response.json()["days"]) == 2


@pytest.mark.django_db
def test_availability_api_returns_validation_error(client, availability_setup):
    property_, rate_plan = availability_setup

    response = client.get(
        reverse("tenancy:availability", kwargs={"property_id": property_.id}),
        {"rate_plan": rate_plan.id, "check_in": "not-a-date", "check_out": "2026-11-03"},
    )

    assert response.status_code == 400
    assert "check_in" in response.json()["detail"]

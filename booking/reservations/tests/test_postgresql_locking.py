from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from threading import Barrier

import pytest
from django.db import close_old_connections, connection

from booking.reservations.services.holds import HoldUnavailable, create_hold
from booking.tenancy.models import DailyRate, Inventory, Organization, Property, RatePlan, UnitType


pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(
        connection.vendor != "postgresql",
        reason="PostgreSQL row-locking test requires a PostgreSQL test database",
    ),
]


@pytest.fixture
def locking_setup():
    organization = Organization.objects.create(name="Balkans", slug="balkans-locking")
    property_ = Property.objects.create(
        organization=organization,
        name="Locking Hotel",
        slug="locking-hotel",
    )
    unit_type = UnitType.objects.create(
        property=property_,
        name="Standard Room",
        code="standard-room-locking",
    )
    rate_plan = RatePlan.objects.create(
        property=property_,
        unit_type=unit_type,
        name="Flexible",
        code="flexible-locking",
    )
    for day in (date(2026, 11, 1), date(2026, 11, 2)):
        Inventory.objects.create(
            property=property_,
            unit_type=unit_type,
            date=day,
            total_capacity=5,
            blocked_capacity=0,
        )
        DailyRate.objects.create(
            rate_plan=rate_plan,
            date=day,
            amount=Decimal("1500.00"),
        )
    return property_, unit_type, rate_plan


def test_concurrent_holds_cannot_exceed_postgresql_capacity(locking_setup):
    property_, unit_type, rate_plan = locking_setup
    ready = Barrier(2)

    def attempt_hold():
        close_old_connections()
        try:
            ready.wait(timeout=10)
            hold, _ = create_hold(
                property_id=property_.id,
                unit_type_id=unit_type.id,
                rate_plan_id=rate_plan.id,
                check_in=date(2026, 11, 1),
                check_out=date(2026, 11, 3),
                quantity=3,
            )
            return "success", hold.pk
        except HoldUnavailable:
            return "unavailable", None
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = [
            future.result(timeout=30)
            for future in [executor.submit(attempt_hold), executor.submit(attempt_hold)]
        ]

    assert [result[0] for result in results].count("success") == 1
    assert [result[0] for result in results].count("unavailable") == 1

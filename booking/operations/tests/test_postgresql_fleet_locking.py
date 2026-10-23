from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from threading import Barrier

import pytest
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection
from django.utils import timezone

from booking.operations.models import ParkingLot, ParkingReservation, ParkingSpace, VehicleRentalBooking, VehicleRentalRate
from booking.operations.services.fleet_reservations import (
    ACTIVE_PARKING_STATUSES,
    ACTIVE_RENTAL_STATUSES,
    save_parking_reservation,
    save_rental_booking,
)
from booking.tenancy.models import Organization, Property, Vehicle


pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(
        connection.vendor != "postgresql",
        reason="Fleet PostgreSQL locking tests require a PostgreSQL test database",
    ),
]


@pytest.fixture
def fleet_locking_setup():
    organization = Organization.objects.create(name="Fleet Locking Group", slug="fleet-locking-group")
    property_ = Property.objects.create(
        organization=organization,
        name="Fleet Locking Hotel",
        slug="fleet-locking-hotel",
    )
    vehicle = Vehicle.objects.create(
        property=property_,
        code="locking-vehicle",
        name="Locking Vehicle",
        vehicle_class="economy",
        online_enabled=True,
    )
    rate = VehicleRentalRate.objects.create(
        vehicle=vehicle,
        name="Locking Rate",
        daily_rate=Decimal("100"),
        deposit_amount=Decimal("500"),
    )
    lot = ParkingLot.objects.create(
        property=property_,
        code="locking-lot",
        name="Locking Lot",
        capacity=1,
    )
    space = ParkingSpace.objects.create(parking_lot=lot, code="LOCK-01")
    start = timezone.now() + timedelta(days=2)
    return {
        "property_id": property_.id,
        "vehicle_id": vehicle.id,
        "rate_id": rate.id,
        "lot_id": lot.id,
        "space_id": space.id,
        "start": start,
    }


def _run_parallel(attempt):
    ready = Barrier(2)

    def worker():
        close_old_connections()
        try:
            ready.wait(timeout=10)
            return attempt()
        except ValidationError:
            return "conflict"
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(worker), executor.submit(worker)]
        return [future.result(timeout=30) for future in futures]


def _assert_postgresql_backend():
    assert connection.vendor == "postgresql", (
        "Fleet locking evidence must run against PostgreSQL, not the local SQLite fallback"
    )


def test_concurrent_vehicle_rental_bookings_allow_only_one_active_record(fleet_locking_setup):
    _assert_postgresql_backend()
    data = fleet_locking_setup
    start = data["start"]

    def attempt():
        booking = VehicleRentalBooking(
            property_id=data["property_id"],
            vehicle_id=data["vehicle_id"],
            rental_rate_id=data["rate_id"],
            customer_name="Concurrent Rental",
            pickup_at=start,
            dropoff_at=start + timedelta(days=2),
            daily_rate=Decimal("100"),
            total_amount=Decimal("200"),
            deposit_amount=Decimal("500"),
        )
        saved = save_rental_booking(booking)
        return "success", saved.pk

    results = _run_parallel(attempt)

    assert [result[0] if isinstance(result, tuple) else result for result in results].count("success") == 1
    assert results.count("conflict") == 1
    assert VehicleRentalBooking.objects.filter(
        vehicle_id=data["vehicle_id"],
        status__in=ACTIVE_RENTAL_STATUSES,
    ).count() == 1


def test_concurrent_parking_reservations_allow_only_one_active_record(fleet_locking_setup):
    _assert_postgresql_backend()
    data = fleet_locking_setup
    start = data["start"]

    def attempt():
        reservation = ParkingReservation(
            property_id=data["property_id"],
            parking_lot_id=data["lot_id"],
            parking_space_id=data["space_id"],
            customer_name="Concurrent Parking",
            start_at=start,
            end_at=start + timedelta(hours=3),
        )
        saved = save_parking_reservation(reservation)
        return "success", saved.pk

    results = _run_parallel(attempt)

    assert [result[0] if isinstance(result, tuple) else result for result in results].count("success") == 1
    assert results.count("conflict") == 1
    assert ParkingReservation.objects.filter(
        parking_lot_id=data["lot_id"],
        parking_space_id=data["space_id"],
        status__in=ACTIVE_PARKING_STATUSES,
    ).count() == 1

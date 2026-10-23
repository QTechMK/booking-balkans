from django.core.exceptions import ValidationError
from django.db import transaction

from ..models import ParkingLot, ParkingReservation, VehicleRentalBooking


ACTIVE_RENTAL_STATUSES = [
    VehicleRentalBooking.Status.PENDING,
    VehicleRentalBooking.Status.CONFIRMED,
    VehicleRentalBooking.Status.ACTIVE,
]
ACTIVE_PARKING_STATUSES = [
    ParkingReservation.Status.PENDING,
    ParkingReservation.Status.CONFIRMED,
    ParkingReservation.Status.CHECKED_IN,
]


@transaction.atomic
def save_rental_booking(booking):
    """Persist a rental booking while serializing the vehicle availability check."""
    vehicle = booking.vehicle.__class__.objects.select_for_update().get(pk=booking.vehicle_id)
    booking.vehicle = vehicle
    conflict = VehicleRentalBooking.objects.filter(
        vehicle_id=booking.vehicle_id,
        pickup_at__lt=booking.dropoff_at,
        dropoff_at__gt=booking.pickup_at,
        status__in=ACTIVE_RENTAL_STATUSES,
    ).exclude(pk=booking.pk).exists()
    if conflict:
        raise ValidationError({"vehicle": "Bu zaman aralığında araç başka bir kiralamaya ayrılmıştır."})
    booking.full_clean()
    booking.save()
    return booking


@transaction.atomic
def save_parking_reservation(reservation):
    """Persist a parking reservation while serializing lot capacity checks."""
    lot = ParkingLot.objects.select_for_update().get(pk=reservation.parking_lot_id)
    reservation.parking_lot = lot
    overlapping = ParkingReservation.objects.filter(
        parking_lot_id=reservation.parking_lot_id,
        start_at__lt=reservation.end_at,
        end_at__gt=reservation.start_at,
        status__in=ACTIVE_PARKING_STATUSES,
    ).exclude(pk=reservation.pk)
    if reservation.parking_space_id and overlapping.filter(parking_space_id=reservation.parking_space_id).exists():
        raise ValidationError({"parking_space": "Bu zaman aralığında park yeri başka bir rezervasyona ayrılmıştır."})
    if not reservation.parking_space_id and lot.capacity and overlapping.count() >= lot.capacity:
        raise ValidationError({"parking_lot": "Bu zaman aralığında otopark kapasitesi doludur."})
    reservation.full_clean()
    reservation.save()
    return reservation

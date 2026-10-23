from booking.operations.models import RentalNotification, VehicleRentalBooking


def queue_rental_notifications(booking: VehicleRentalBooking):
    """Queue customer notifications; delivery is performed by a worker/command."""
    queued = []
    if booking.customer_email:
        notification, _ = RentalNotification.objects.get_or_create(
            booking=booking,
            channel="email",
            template_code="rental.booking.received",
            recipient=booking.customer_email,
            defaults={"status": "pending"},
        )
        queued.append(notification)
    if booking.customer_phone:
        notification, _ = RentalNotification.objects.get_or_create(
            booking=booking,
            channel="whatsapp",
            template_code="rental.booking.received",
            recipient=booking.customer_phone,
            defaults={"status": "pending"},
        )
        queued.append(notification)
    return queued

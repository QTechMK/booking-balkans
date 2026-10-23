from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from booking.operations.models import RentalAuditEvent, RentalPrivacyEvent, VehicleRentalBooking


class Command(BaseCommand):
    help = "Anonimleştirilecek süresi dolmuş araç kiralama verilerini listeler veya işler."

    def add_arguments(self, parser):
        parser.add_argument("--execute", action="store_true", help="Anonymization işlemini gerçekten uygula.")

    def handle(self, *args, **options):
        queryset = VehicleRentalBooking.objects.filter(
            data_retention_until__lt=timezone.localdate(),
        ).exclude(customer_name="Anonim müşteri").select_related("driver_profile")
        total = queryset.count()
        if not options["execute"]:
            self.stdout.write(self.style.WARNING(f"{total} expired records found; use --execute to apply."))
            return
        for booking in queryset.iterator():
            with transaction.atomic():
                driver = booking.driver_profile
                if driver:
                    if driver.license_document:
                        default_storage.delete(driver.license_document.name)
                    driver.full_name = "Anonim müşteri"
                    driver.email = ""
                    driver.phone = ""
                    driver.license_number = ""
                    driver.identity_document_ref = ""
                    driver.license_document = ""
                    driver.notes = ""
                    driver.save(update_fields=["full_name", "email", "phone", "license_number", "identity_document_ref", "license_document", "notes", "updated_at"])
                booking.customer_name = "Anonim müşteri"
                booking.customer_email = ""
                booking.customer_phone = ""
                booking.license_number = ""
                booking.driver_license_country = ""
                booking.privacy_consent_at = None
                booking.save(update_fields=["customer_name", "customer_email", "customer_phone", "license_number", "driver_license_country", "privacy_consent_at", "updated_at"])
                RentalPrivacyEvent.objects.create(
                    property=booking.property, booking=booking, driver_profile=driver,
                    event_type=RentalPrivacyEvent.EventType.DELETION_REQUEST,
                    policy_version=booking.privacy_policy_version, source="retention_job",
                    metadata={"reason": "retention_expired"},
                )
                RentalAuditEvent.objects.create(
                    property=booking.property, booking=booking, action="privacy_retention_purged",
                    source="retention_job", payload={"retention_until": str(booking.data_retention_until)},
                )
        self.stdout.write(self.style.SUCCESS(f"{total} records anonymized."))

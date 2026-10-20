from datetime import date
from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.core.management.base import CommandError
from django.db import transaction

from booking.tenancy.models import DailyRate
from booking.tenancy.models import Inventory
from booking.tenancy.models import Organization
from booking.tenancy.models import Property
from booking.tenancy.models import RatePlan
from booking.tenancy.models import RateRestriction
from booking.tenancy.models import Season
from booking.tenancy.models import Unit
from booking.tenancy.models import UnitStatus
from booking.tenancy.models import UnitType
from booking.tenancy.models import UnitTypeKind


class Command(BaseCommand):
    help = "Create idempotent demo hotel inventory and rate data for Booking Balkans."

    def add_arguments(self, parser):
        parser.add_argument(
            "--start-date",
            type=date.fromisoformat,
            default=date.today(),
            help="First inventory date in YYYY-MM-DD format (default: today).",
        )
        parser.add_argument(
            "--days",
            type=int,
            default=365,
            help="Number of inventory and rate days to create (default: 365).",
        )
        parser.add_argument(
            "--price",
            type=Decimal,
            default=Decimal("1500.00"),
            help="Nightly TRY price (default: 1500.00).",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        start_date = options["start_date"]
        days = options["days"]
        price = options["price"]
        if days < 1:
            raise CommandError("--days must be positive")
        if price < 0:
            raise CommandError("--price cannot be negative")

        organization, _ = Organization.objects.get_or_create(
            slug="booking-balkans-demo",
            defaults={
                "name": "Booking Balkans Demo",
                "business_type_default": "OTL-S",
                "country": "TR",
                "default_currency": "TRY",
                "timezone": "Europe/Istanbul",
            },
        )
        property_, _ = Property.objects.get_or_create(
            organization=organization,
            slug="booking-balkans-demo-hotel",
            defaults={
                "name": "Booking Balkans Demo Hotel",
                "business_type": "OTL-S",
                "city": "Istanbul",
                "country": "TR",
                "timezone": "Europe/Istanbul",
                "currency": "TRY",
            },
        )
        unit_type, _ = UnitType.objects.get_or_create(
            property=property_,
            code="standard-room",
            defaults={
                "name": "Standard Room",
                "kind": UnitTypeKind.ROOM,
                "inventory_mode": "unit",
                "capacity_per_unit": 1,
                "max_adults": 2,
                "max_children": 1,
            },
        )
        for number in range(1, 11):
            Unit.objects.get_or_create(
                property=property_,
                code=f"{100 + number}",
                defaults={
                    "unit_type": unit_type,
                    "name": f"Standard Room {100 + number}",
                    "status": UnitStatus.ACTIVE,
                },
            )

        rate_plan, _ = RatePlan.objects.get_or_create(
            property=property_,
            code="standard-flexible",
            defaults={
                "unit_type": unit_type,
                "name": "Standard Flexible",
                "cancellation_policy": "Free cancellation before arrival",
                "is_refundable": True,
                "max_adults": 2,
                "max_children": 1,
                "currency": "TRY",
            },
        )
        end_date = start_date + timedelta(days=days - 1)
        Season.objects.get_or_create(
            property=property_,
            code="demo-season",
            defaults={
                "name": "Demo Season",
                "start_date": start_date,
                "end_date": end_date,
                "priority": 1,
            },
        )

        for offset in range(days):
            day = start_date + timedelta(days=offset)
            Inventory.objects.get_or_create(
                property=property_,
                unit_type=unit_type,
                date=day,
                defaults={"total_capacity": 10, "blocked_capacity": 0},
            )
            DailyRate.objects.get_or_create(
                rate_plan=rate_plan,
                date=day,
                defaults={"amount": price, "min_nights": 1},
            )
            RateRestriction.objects.get_or_create(
                rate_plan=rate_plan,
                date=day,
                defaults={"min_nights": 1},
            )

        self.stdout.write(self.style.SUCCESS("Booking Balkans demo data is ready."))
        self.stdout.write(f"Organization ID: {organization.id}")
        self.stdout.write(f"Property ID: {property_.id}")
        self.stdout.write(f"UnitType ID: {unit_type.id}")
        self.stdout.write(f"RatePlan ID: {rate_plan.id}")
        self.stdout.write(f"Inventory range: {start_date} to {end_date}")

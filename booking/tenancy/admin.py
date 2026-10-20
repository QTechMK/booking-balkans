from django.contrib import admin

from .models import Bed
from .models import DailyRate
from .models import Inventory
from .models import Membership
from .models import Organization
from .models import Property
from .models import RatePlan
from .models import RateRestriction
from .models import Season
from .models import Unit
from .models import UnitType


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ["name", "business_type_default", "country", "is_active"]
    list_filter = ["business_type_default", "country", "is_active"]
    search_fields = ["name", "slug"]
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Property)
class PropertyAdmin(admin.ModelAdmin):
    list_display = ["name", "organization", "business_type", "city", "is_active"]
    list_filter = ["business_type", "country", "is_active"]
    search_fields = ["name", "slug", "organization__name", "city"]
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ["user", "organization", "property", "role", "is_active"]
    list_filter = ["role", "is_active"]
    search_fields = ["user__username", "user__email", "organization__name"]
    autocomplete_fields = ["user", "organization", "property"]


@admin.register(UnitType)
class UnitTypeAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "property",
        "kind",
        "inventory_mode",
        "capacity_per_unit",
        "is_active",
    ]
    list_filter = ["kind", "inventory_mode", "is_active"]
    search_fields = ["name", "code", "property__name", "property__organization__name"]
    autocomplete_fields = ["property"]
    prepopulated_fields = {"code": ("name",)}


@admin.register(Unit)
class UnitAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "property", "unit_type", "status", "is_active"]
    list_filter = ["status", "is_active", "unit_type__kind"]
    search_fields = ["code", "name", "property__name", "unit_type__name"]
    autocomplete_fields = ["property", "unit_type"]


@admin.register(Bed)
class BedAdmin(admin.ModelAdmin):
    list_display = ["code", "unit", "status", "is_active"]
    list_filter = ["status", "is_active"]
    search_fields = ["code", "unit__code", "unit__property__name"]
    autocomplete_fields = ["unit"]


@admin.register(Inventory)
class InventoryAdmin(admin.ModelAdmin):
    list_display = [
        "date",
        "property",
        "unit_type",
        "total_capacity",
        "blocked_capacity",
        "is_closed",
    ]
    list_filter = ["is_closed", "property", "unit_type"]
    search_fields = ["property__name", "unit_type__name"]
    autocomplete_fields = ["property", "unit_type"]
    date_hierarchy = "date"


@admin.register(RatePlan)
class RatePlanAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "property",
        "unit_type",
        "meal_plan",
        "is_refundable",
        "currency",
        "is_active",
    ]
    list_filter = ["meal_plan", "is_refundable", "is_active"]
    search_fields = ["name", "code", "property__name", "unit_type__name"]
    autocomplete_fields = ["property", "unit_type"]
    prepopulated_fields = {"code": ("name",)}


@admin.register(Season)
class SeasonAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "property",
        "start_date",
        "end_date",
        "priority",
        "is_active",
    ]
    list_filter = ["is_active", "property"]
    search_fields = ["name", "code", "property__name"]
    autocomplete_fields = ["property"]
    prepopulated_fields = {"code": ("name",)}
    date_hierarchy = "start_date"


@admin.register(DailyRate)
class DailyRateAdmin(admin.ModelAdmin):
    list_display = [
        "date",
        "rate_plan",
        "amount",
        "min_nights",
        "max_nights",
        "is_closed",
    ]
    list_filter = ["is_closed", "rate_plan__property", "rate_plan__unit_type"]
    search_fields = ["rate_plan__name", "rate_plan__code"]
    autocomplete_fields = ["rate_plan"]
    date_hierarchy = "date"


@admin.register(RateRestriction)
class RateRestrictionAdmin(admin.ModelAdmin):
    list_display = [
        "date",
        "rate_plan",
        "stop_sell",
        "close_to_arrival",
        "close_to_departure",
        "min_nights",
        "max_nights",
    ]
    list_filter = [
        "stop_sell",
        "close_to_arrival",
        "close_to_departure",
        "rate_plan__property",
    ]
    search_fields = ["rate_plan__name", "rate_plan__code"]
    autocomplete_fields = ["rate_plan"]
    date_hierarchy = "date"

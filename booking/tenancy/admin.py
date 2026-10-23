from django.contrib import admin

from .models import Bed
from .models import BedType, BoardType, HotelPhoto, PropertySettings, RateType, RoomAmenity, RoomGroup, RoomLocation, RoomPhoto, RoomView
from .models import CancellationOptionRule, ChannelRateRule
from .models import DailyRate
from .models import Inventory
from .models import Membership
from .models import Organization
from .models import Property
from .models import PropertyModuleLicense
from .models import PriceParityObservation
from .models import RatePlan, RatePlanChannel, RatePlanSeason
from .models import RateRestriction
from .models import Season
from .models import Unit, Vehicle
from .models import UnitType


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ["name", "business_type_default", "country", "is_active"]
    list_filter = ["business_type_default", "country", "is_active"]
    search_fields = ["name", "slug"]
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Property)
class PropertyAdmin(admin.ModelAdmin):
    list_display = ["name", "organization", "business_type", "city", "fleet_widget_key", "is_active"]
    list_filter = ["business_type", "country", "is_active"]
    search_fields = ["name", "slug", "organization__name", "city"]
    prepopulated_fields = {"slug": ("name",)}
    readonly_fields = ["fleet_widget_key"]


@admin.register(PropertyModuleLicense)
class PropertyModuleLicenseAdmin(admin.ModelAdmin):
    list_display = ["property", "module", "plan_code", "is_enabled", "starts_at", "ends_at"]
    list_filter = ["module", "is_enabled"]
    search_fields = ["property__name", "property__organization__name", "plan_code"]


@admin.register(PropertySettings)
class PropertySettingsAdmin(admin.ModelAdmin):
    list_display = ["property", "reservation_email", "check_in_time", "check_out_time", "system_date"]
    search_fields = ["property__name", "reservation_email", "accounting_email"]
    autocomplete_fields = ["property"]


class PropertyDictionaryAdmin(admin.ModelAdmin):
    list_display = ["name", "code", "property", "is_active"]
    list_filter = ["is_active", "property"]
    search_fields = ["name", "code", "property__name"]
    autocomplete_fields = ["property"]


for _model in [RoomGroup, BedType, RoomView, RoomLocation, RoomAmenity, BoardType, RateType]:
    admin.site.register(_model, PropertyDictionaryAdmin)


@admin.register(RoomPhoto)
class RoomPhotoAdmin(admin.ModelAdmin):
    list_display = ["property", "unit_type", "unit", "is_primary", "sort_order"]
    list_filter = ["is_primary", "property"]
    search_fields = ["image_url", "alt_text", "property__name"]
    autocomplete_fields = ["property", "unit_type", "unit"]


@admin.register(HotelPhoto)
class HotelPhotoAdmin(admin.ModelAdmin):
    list_display = ["property", "category", "alt_text", "is_primary", "sort_order", "show_online"]
    list_filter = ["category", "is_primary", "show_online", "property"]
    search_fields = ["image_url", "alt_text", "category", "property__name"]
    autocomplete_fields = ["property"]


@admin.register(CancellationOptionRule)
class CancellationOptionRuleAdmin(admin.ModelAdmin):
    list_display = ["property", "rate_type", "name", "cancellation_until_hours", "penalty_type", "penalty_value", "is_active"]
    list_filter = ["property", "rate_type", "penalty_type", "is_active"]
    search_fields = ["name", "property__name"]
    autocomplete_fields = ["property", "rate_type"]


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
    autocomplete_fields = ["property", "room_group"]
    filter_horizontal = ["amenities"]
    prepopulated_fields = {"code": ("name",)}


@admin.register(Unit)
class UnitAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "property", "unit_type", "status", "is_active"]
    list_filter = ["status", "is_active", "unit_type__kind"]
    search_fields = ["code", "name", "property__name", "unit_type__name"]
    autocomplete_fields = ["property", "unit_type", "bed_type", "room_view", "room_location"]


@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "property", "vehicle_type", "plate_number", "passenger_capacity", "daily_rate", "status", "is_active"]
    list_filter = ["property", "vehicle_type", "fuel_type", "status", "is_active"]
    search_fields = ["code", "name", "plate_number", "property__name"]
    autocomplete_fields = ["property"]


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
        "min_nights",
        "max_nights",
        "season_label",
        "is_active",
    ]
    list_filter = ["meal_plan", "is_refundable", "is_active"]
    search_fields = ["name", "code", "property__name", "unit_type__name"]
    autocomplete_fields = ["property", "unit_type", "board_type", "rate_type"]
    prepopulated_fields = {"code": ("name",)}


@admin.register(RatePlanSeason)
class RatePlanSeasonAdmin(admin.ModelAdmin):
    list_display = ("rate_plan", "name", "valid_from", "valid_until", "min_nights", "max_nights", "price_factor", "is_active")
    list_filter = ("is_active", "rate_plan__property")
    search_fields = ("name", "rate_plan__name")
    autocomplete_fields = ("rate_plan",)
    date_hierarchy = "valid_from"


@admin.register(RatePlanChannel)
class RatePlanChannelAdmin(admin.ModelAdmin):
    list_display = ("rate_plan", "channel", "external_code", "is_active")
    list_filter = ("is_active", "channel__property")
    search_fields = ("rate_plan__name", "channel__name", "external_code")
    autocomplete_fields = ("rate_plan", "channel")


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


@admin.register(ChannelRateRule)
class ChannelRateRuleAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "property",
        "channel",
        "rate_plan",
        "rule_type",
        "adjustment",
        "priority",
        "is_active",
    ]
    list_filter = ["rule_type", "is_active", "property", "channel"]
    search_fields = ["name", "channel__name", "rate_plan__name", "property__name"]
    autocomplete_fields = ["property", "channel", "rate_plan"]


@admin.register(PriceParityObservation)
class PriceParityObservationAdmin(admin.ModelAdmin):
    list_display = [
        "observed_at",
        "property",
        "competitor_name",
        "check_in",
        "check_out",
        "direct_amount",
        "competitor_amount",
        "terms_match",
        "status",
    ]
    list_filter = ["status", "terms_match", "property", "competitor_name"]
    search_fields = ["competitor_name", "property__name", "rate_plan__name"]
    autocomplete_fields = ["property", "rate_plan", "channel"]
    date_hierarchy = "observed_at"
    readonly_fields = ["observed_at", "status"]

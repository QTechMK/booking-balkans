from django.contrib import admin

from .models import Guest
from .models import Reservation
from .models import ReservationHold
from .models import ReservationItem


@admin.register(Guest)
class GuestAdmin(admin.ModelAdmin):
    list_display = ["first_name", "last_name", "email", "phone", "property"]
    list_filter = ["property"]
    search_fields = ["first_name", "last_name", "email", "phone"]
    autocomplete_fields = ["property"]


@admin.register(Reservation)
class ReservationAdmin(admin.ModelAdmin):
    list_display = [
        "reference",
        "property",
        "guest",
        "check_in",
        "check_out",
        "status",
        "stay_status",
        "source",
        "total_amount",
    ]
    list_filter = ["status", "source", "property", "currency"]
    search_fields = ["reference", "guest__first_name", "guest__last_name", "guest__email"]
    autocomplete_fields = ["property", "guest", "created_by"]
    date_hierarchy = "check_in"
    readonly_fields = ["reference", "created_at", "updated_at"]


@admin.register(ReservationItem)
class ReservationItemAdmin(admin.ModelAdmin):
    list_display = [
        "reservation",
        "unit_type",
        "rate_plan",
        "unit",
        "quantity",
        "stay_status",
        "checked_in_at",
        "checked_out_at",
        "total_amount",
    ]
    list_filter = ["unit_type", "rate_plan", "stay_status"]
    search_fields = ["reservation__reference", "unit_type__name", "rate_plan__name"]
    autocomplete_fields = [
        "reservation",
        "unit_type",
        "rate_plan",
        "unit",
        "checked_in_by",
        "checked_out_by",
    ]


@admin.register(ReservationHold)
class ReservationHoldAdmin(admin.ModelAdmin):
    list_display = [
        "token",
        "property",
        "unit_type",
        "rate_plan",
        "check_in",
        "check_out",
        "quantity",
        "expires_at",
        "status",
    ]
    list_filter = ["status", "property", "unit_type"]
    search_fields = ["token", "property__name", "unit_type__name", "rate_plan__name"]
    autocomplete_fields = ["property", "unit_type", "rate_plan", "created_by"]
    readonly_fields = ["token", "created_at", "updated_at"]
    date_hierarchy = "check_in"

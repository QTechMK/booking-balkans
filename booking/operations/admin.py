from django.contrib import admin

from .models import GuestProfileExtension, HousekeepingTask, MaintenanceTicket, OperationalTask, OnlineBookingSettings, TaskGroup, TaskLocation, UnitHousekeepingState


@admin.register(HousekeepingTask)
class HousekeepingTaskAdmin(admin.ModelAdmin):
    list_display = ("unit", "status", "priority", "assigned_to", "updated_at")
    list_filter = ("property", "status", "priority")
    search_fields = ("unit__code", "note")


@admin.register(UnitHousekeepingState)
class UnitHousekeepingStateAdmin(admin.ModelAdmin):
    list_display = ("unit", "status", "changed_by", "changed_at")
    list_filter = ("status", "unit__property")
    search_fields = ("unit__code", "note")
    autocomplete_fields = ("unit", "changed_by")


@admin.register(TaskGroup, TaskLocation)
class TaskDictionaryAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "property", "is_active")
    list_filter = ("property", "is_active")
    search_fields = ("name", "code", "property__name")
    autocomplete_fields = ("property",)


@admin.register(OperationalTask)
class OperationalTaskAdmin(admin.ModelAdmin):
    list_display = ("title", "property", "status", "priority", "assigned_to", "due_at", "source")
    list_filter = ("property", "status", "priority", "source")
    search_fields = ("title", "description", "unit__code")
    autocomplete_fields = ("property", "group", "location", "unit", "assigned_to")


@admin.register(MaintenanceTicket)
class MaintenanceTicketAdmin(admin.ModelAdmin):
    list_display = ("title", "property", "unit", "status", "priority", "assigned_to")
    list_filter = ("property", "status", "priority")
    search_fields = ("title", "description")


@admin.register(GuestProfileExtension)
class GuestProfileExtensionAdmin(admin.ModelAdmin):
    list_display = ("guest", "vip", "gdpr_confirmed", "email_confirmed", "phone_confirmed")
    list_filter = ("vip", "gdpr_confirmed")
    search_fields = ("guest__first_name", "guest__last_name", "guest__email")


@admin.register(OnlineBookingSettings)
class OnlineBookingSettingsAdmin(admin.ModelAdmin):
    list_display = ("property", "booking_page_active", "online_checkin_active", "online_payment_active", "guest_portal_active")
    list_filter = ("booking_page_active", "online_checkin_active", "guest_portal_active")

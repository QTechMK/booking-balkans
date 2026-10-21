from django.contrib import admin

from .models import AccessPermission, GuestProfileExtension, HousekeepingTask, MaintenanceTicket, OperationalTask, OnlineBookingSettings, PropertyRole, TaskGroup, TaskLocation, UnitHousekeepingState, UserAccessLog, UserPropertyAccess


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


@admin.register(AccessPermission)
class AccessPermissionAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "module", "action", "is_active")
    list_filter = ("module", "action", "is_active")
    search_fields = ("code", "name")


@admin.register(PropertyRole)
class PropertyRoleAdmin(admin.ModelAdmin):
    list_display = ("name", "property", "department", "is_active")
    list_filter = ("property", "is_active")
    search_fields = ("name", "department", "property__name")
    autocomplete_fields = ("property", "permissions")


@admin.register(UserPropertyAccess)
class UserPropertyAccessAdmin(admin.ModelAdmin):
    list_display = ("user", "property", "role", "is_active", "two_factor_required", "valid_until")
    list_filter = ("property", "role", "is_active", "two_factor_required")
    search_fields = ("user__username", "user__email", "property__name", "role__name")
    autocomplete_fields = ("user", "property", "role")


@admin.register(UserAccessLog)
class UserAccessLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "user", "property", "event", "successful", "ip_address")
    list_filter = ("event", "successful", "property")
    search_fields = ("user__username", "ip_address", "event")
    readonly_fields = ("created_at",)


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

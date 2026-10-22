from django.contrib import admin

from .models import AccessPermission, DepartmentDefinition, FrontOfficeCallRequest, GuestLoyaltyAccount, GuestProfileExtension, GuestSegment, HousekeepingTask, HousekeepingTaskHistory, LoyaltyTier, LoyaltyTransaction, MaintenanceTicket, MaintenanceTicketHistory, MarketingCampaign, MarketingDelivery, MessageTemplate, OperationalTask, OnlineBookingSettings, PropertyRole, PropertyService, RevenueCode, ServiceRequest, SupportAuditEvent, SupportEducationRequest, SupportFAQCategory, SupportFAQItem, SupportHelpLink, SupportReferral, SupportTicket, SupportTicketMessage, SupportVideo, SupportVideoCategory, TaskGroup, TaskLocation, UnitHousekeepingState, UserAccessLog, UserPropertyAccess


@admin.register(HousekeepingTask)
class HousekeepingTaskAdmin(admin.ModelAdmin):
    list_display = ("unit", "status", "priority", "assigned_to", "supervisor_approved_by", "updated_at")
    list_filter = ("property", "status", "priority")
    search_fields = ("unit__code", "note")


@admin.register(HousekeepingTaskHistory)
class HousekeepingTaskHistoryAdmin(admin.ModelAdmin):
    list_display = ("created_at", "unit", "status", "shift", "assigned_to", "changed_by")
    list_filter = ("property", "status", "shift")
    search_fields = ("unit__code", "note")
    readonly_fields = ("created_at",)


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
    list_display = ("user", "property", "role", "is_active", "two_factor_required", "allowed_ip", "device_label", "financial_access", "valid_until")
    list_filter = ("property", "role", "is_active", "two_factor_required")
    search_fields = ("user__username", "user__email", "property__name", "role__name")
    autocomplete_fields = ("user", "property", "role")
    exclude = ("pin_hash",)


@admin.register(UserAccessLog)
class UserAccessLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "actor", "user", "property", "event", "successful", "ip_address", "metadata")
    list_filter = ("event", "successful", "property")
    search_fields = ("user__username", "ip_address", "event")
    readonly_fields = ("created_at", "metadata")


@admin.register(MaintenanceTicket)
class MaintenanceTicketAdmin(admin.ModelAdmin):
    list_display = ("title", "property", "unit", "status", "priority", "assigned_to")
    list_filter = ("property", "status", "priority")
    search_fields = ("title", "description")


@admin.register(MaintenanceTicketHistory)
class MaintenanceTicketHistoryAdmin(admin.ModelAdmin):
    list_display = ("created_at", "ticket", "status", "assigned_to", "changed_by", "actual_cost")
    list_filter = ("property", "status")
    search_fields = ("ticket__title", "resolution_note")
    readonly_fields = ("created_at",)


@admin.register(GuestProfileExtension)
class GuestProfileExtensionAdmin(admin.ModelAdmin):
    list_display = ("guest", "vip", "gdpr_confirmed", "email_confirmed", "phone_confirmed")
    list_filter = ("vip", "gdpr_confirmed")
    search_fields = ("guest__first_name", "guest__last_name", "guest__email")


@admin.register(LoyaltyTier)
class LoyaltyTierAdmin(admin.ModelAdmin):
    list_display = ("name", "property", "minimum_points", "discount_percent", "is_active")
    list_filter = ("property", "is_active")
    search_fields = ("name", "code", "property__name")
    autocomplete_fields = ("property",)


@admin.register(GuestLoyaltyAccount)
class GuestLoyaltyAccountAdmin(admin.ModelAdmin):
    list_display = ("membership_number", "guest", "property", "tier", "points_balance")
    list_filter = ("property", "tier")
    search_fields = ("membership_number", "guest__first_name", "guest__last_name", "guest__email")
    autocomplete_fields = ("guest", "property", "tier")


@admin.register(LoyaltyTransaction)
class LoyaltyTransactionAdmin(admin.ModelAdmin):
    list_display = ("created_at", "account", "kind", "points", "created_by")
    list_filter = ("kind", "account__property")
    search_fields = ("account__membership_number", "account__guest__email", "note")
    autocomplete_fields = ("account", "created_by")
    readonly_fields = ("created_at",)


@admin.register(GuestSegment)
class GuestSegmentAdmin(admin.ModelAdmin):
    list_display = ("name", "property", "is_active", "updated_at")
    list_filter = ("property", "is_active")
    search_fields = ("name", "property__name")
    autocomplete_fields = ("property",)


@admin.register(MessageTemplate)
class MessageTemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "channel", "property", "is_active")
    list_filter = ("channel", "property", "is_active")
    search_fields = ("name", "code", "body")
    autocomplete_fields = ("property",)


@admin.register(MarketingCampaign)
class MarketingCampaignAdmin(admin.ModelAdmin):
    list_display = ("name", "property", "status", "segment", "template", "scheduled_at")
    list_filter = ("property", "status")
    search_fields = ("name", "property__name")
    autocomplete_fields = ("property", "segment", "template", "created_by")


@admin.register(MarketingDelivery)
class MarketingDeliveryAdmin(admin.ModelAdmin):
    list_display = ("campaign", "guest", "channel", "recipient", "status", "queued_at", "sent_at")
    list_filter = ("channel", "status", "campaign__property")
    search_fields = ("recipient", "guest__first_name", "guest__last_name", "campaign__name")
    autocomplete_fields = ("campaign", "guest")


@admin.register(OnlineBookingSettings)
class OnlineBookingSettingsAdmin(admin.ModelAdmin):
    list_display = ("property", "booking_page_active", "online_checkin_active", "online_payment_active", "payment_provider", "deposit_percent", "guest_portal_active")
    list_filter = ("booking_page_active", "online_checkin_active", "guest_portal_active")


@admin.register(PropertyService)
class PropertyServiceAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "property", "price", "currency", "show_online", "is_active")
    list_filter = ("kind", "property", "show_online", "is_active")
    search_fields = ("name", "code", "property__name")
    autocomplete_fields = ("property",)


@admin.register(ServiceRequest)
class ServiceRequestAdmin(admin.ModelAdmin):
    list_display = ("reservation", "service", "quantity", "status", "scheduled_at", "created_at")
    list_filter = ("status", "service__kind", "reservation__property")
    search_fields = ("reservation__reference", "reservation__guest__email", "service__name")
    autocomplete_fields = ("reservation", "service")


@admin.register(SupportTicket)
class SupportTicketAdmin(admin.ModelAdmin):
    list_display = ("subject", "property", "status", "priority", "created_by", "assigned_to", "created_at")
    list_filter = ("property", "status", "priority", "module")
    search_fields = ("subject", "message", "created_by__username")
    autocomplete_fields = ("property", "created_by", "assigned_to")


@admin.register(SupportTicketMessage)
class SupportTicketMessageAdmin(admin.ModelAdmin):
    list_display = ("ticket", "author", "is_internal", "created_at")
    list_filter = ("is_internal", "ticket__property")
    search_fields = ("body", "ticket__subject")
    autocomplete_fields = ("ticket", "author")


@admin.register(SupportAuditEvent)
class SupportAuditEventAdmin(admin.ModelAdmin):
    list_display = ("ticket", "actor", "event", "created_at")
    list_filter = ("event", "ticket__property")
    readonly_fields = ("created_at",)


@admin.register(SupportFAQCategory, SupportFAQItem, SupportHelpLink, SupportVideoCategory, SupportVideo, SupportEducationRequest, SupportReferral)
class SupportCatalogAdmin(admin.ModelAdmin):
    list_display = ("__str__",)


@admin.register(FrontOfficeCallRequest)
class FrontOfficeCallRequestAdmin(admin.ModelAdmin):
    list_display = ("name", "property", "phone", "status", "callback_at", "created_at")
    list_filter = ("property", "status")
    search_fields = ("name", "phone", "email", "note")
    autocomplete_fields = ("property", "guest", "reservation", "created_by")


@admin.register(DepartmentDefinition, RevenueCode)
class AccountingDefinitionAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "property", "is_active")
    list_filter = ("property", "is_active")
    search_fields = ("code", "name", "property__name")
    autocomplete_fields = ("property",)

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from uuid import uuid4

from booking.reservations.models import Guest, Reservation
from booking.tenancy.models import Property, RatePlan, Unit, UnitType, Vehicle


class HousekeepingStatus(models.TextChoices):
    CLEAN = "clean", _("Clean")
    DIRTY = "dirty", _("Dirty")
    IN_PROGRESS = "in_progress", _("Cleaning")
    INSPECTION = "inspection", _("Inspection")
    OUT_OF_SERVICE = "out_of_service", _("Out of service")


class TaskPriority(models.TextChoices):
    LOW = "low", _("Low")
    NORMAL = "normal", _("Normal")
    HIGH = "high", _("High")
    URGENT = "urgent", _("Urgent")


class TaskStatus(models.TextChoices):
    OPEN = "open", _("Open")
    IN_PROGRESS = "in_progress", _("In progress")
    WAITING = "waiting", _("Waiting")
    DONE = "done", _("Done")
    CANCELLED = "cancelled", _("Cancelled")


class TaskDictionaryBase(models.Model):
    property = models.ForeignKey(Property, on_delete=models.CASCADE)
    code = models.SlugField(max_length=80)
    name = models.CharField(max_length=160)
    is_active = models.BooleanField(default=True)

    class Meta:
        abstract = True
        ordering = ["property", "name"]


class TaskGroup(TaskDictionaryBase):
    class Meta(TaskDictionaryBase.Meta):
        constraints = [models.UniqueConstraint(fields=["property", "code"], name="unique_task_group_code_per_property")]


class TaskLocation(TaskDictionaryBase):
    class Meta(TaskDictionaryBase.Meta):
        constraints = [models.UniqueConstraint(fields=["property", "code"], name="unique_task_location_code_per_property")]


class OperationalTask(models.Model):
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="operational_tasks")
    group = models.ForeignKey(TaskGroup, on_delete=models.SET_NULL, null=True, blank=True, related_name="tasks")
    location = models.ForeignKey(TaskLocation, on_delete=models.SET_NULL, null=True, blank=True, related_name="tasks")
    unit = models.ForeignKey(Unit, on_delete=models.SET_NULL, null=True, blank=True, related_name="operational_tasks")
    title = models.CharField(max_length=180)
    description = models.TextField(blank=True)
    source = models.CharField(max_length=40, default="manual")
    status = models.CharField(max_length=20, choices=TaskStatus.choices, default=TaskStatus.OPEN)
    priority = models.CharField(max_length=12, choices=TaskPriority.choices, default=TaskPriority.NORMAL)
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="operational_tasks")
    due_at = models.DateTimeField(null=True, blank=True)
    sla_due_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="completed_operational_tasks")
    completion_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["status", "due_at", "-created_at"]
        indexes = [models.Index(fields=["property", "status"]), models.Index(fields=["property", "due_at"])]

    def clean(self):
        from django.core.exceptions import ValidationError
        for field in ("group", "location", "unit"):
            value = getattr(self, f"{field}_id")
            if value and getattr(getattr(self, field), "property_id") != self.property_id:
                raise ValidationError({field: _("Task definition must belong to the same property.")})


class HousekeepingTask(models.Model):
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="housekeeping_tasks")
    unit = models.ForeignKey(Unit, on_delete=models.CASCADE, related_name="housekeeping_tasks")
    status = models.CharField(max_length=24, choices=HousekeepingStatus.choices, default=HousekeepingStatus.DIRTY)
    priority = models.CharField(max_length=12, choices=TaskPriority.choices, default=TaskPriority.NORMAL)
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="housekeeping_tasks")
    shift = models.CharField(max_length=40, blank=True)
    note = models.TextField(blank=True)
    due_at = models.DateTimeField(null=True, blank=True)
    inspected_at = models.DateTimeField(null=True, blank=True)
    inspected_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="inspected_housekeeping_tasks")
    supervisor_approved_at = models.DateTimeField(null=True, blank=True)
    supervisor_approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="approved_housekeeping_tasks")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["status", "-updated_at"]
        indexes = [models.Index(fields=["property", "status"]), models.Index(fields=["unit", "status"])]

    def __str__(self):
        return f"{self.unit.code} - {self.get_status_display()}"


class HousekeepingTaskHistory(models.Model):
    task = models.ForeignKey(HousekeepingTask, on_delete=models.CASCADE, related_name="history")
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="housekeeping_history")
    unit = models.ForeignKey(Unit, on_delete=models.CASCADE, related_name="housekeeping_history")
    status = models.CharField(max_length=24, choices=HousekeepingStatus.choices)
    shift = models.CharField(max_length=40, blank=True)
    note = models.TextField(blank=True)
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="housekeeping_history_assignments")
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="housekeeping_history_changes")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["property", "unit", "created_at"])]


class UnitHousekeepingState(models.Model):
    """Canonical current housekeeping state for a physical room."""

    unit = models.OneToOneField(Unit, on_delete=models.CASCADE, related_name="housekeeping_state")
    status = models.CharField(max_length=24, choices=HousekeepingStatus.choices, default=HousekeepingStatus.CLEAN)
    note = models.TextField(blank=True)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="housekeeping_state_changes")
    changed_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.unit.code} - {self.get_status_display()}"


class MaintenanceStatus(models.TextChoices):
    OPEN = "open", _("Open")
    IN_PROGRESS = "in_progress", _("In progress")
    WAITING = "waiting", _("Waiting")
    RESOLVED = "resolved", _("Resolved")
    CANCELLED = "cancelled", _("Cancelled")


class MaintenanceTicket(models.Model):
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="maintenance_tickets")
    unit = models.ForeignKey(Unit, on_delete=models.CASCADE, null=True, blank=True, related_name="maintenance_tickets")
    title = models.CharField(max_length=180)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=24, choices=MaintenanceStatus.choices, default=MaintenanceStatus.OPEN)
    priority = models.CharField(max_length=12, choices=TaskPriority.choices, default=TaskPriority.NORMAL)
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="maintenance_tickets")
    sla_due_at = models.DateTimeField(null=True, blank=True)
    resolution_note = models.TextField(blank=True)
    estimated_cost = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    actual_cost = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="resolved_maintenance_tickets")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_maintenance_tickets")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["status", "-created_at"]
        indexes = [models.Index(fields=["property", "status"]), models.Index(fields=["property", "sla_due_at"])]


class MaintenanceTicketHistory(models.Model):
    ticket = models.ForeignKey(MaintenanceTicket, on_delete=models.CASCADE, related_name="history")
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="maintenance_history")
    status = models.CharField(max_length=24, choices=MaintenanceStatus.choices)
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="maintenance_history_assignments")
    resolution_note = models.TextField(blank=True)
    estimated_cost = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    actual_cost = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="maintenance_history_changes")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["property", "ticket", "created_at"])]


class GuestProfileExtension(models.Model):
    guest = models.OneToOneField(Guest, on_delete=models.CASCADE, related_name="profile_extension")
    gender = models.CharField(max_length=24, blank=True)
    birth_date = models.DateField(null=True, blank=True)
    nationality = models.CharField(max_length=80, blank=True)
    identity_reference = models.CharField(max_length=120, blank=True)
    passport_number = models.CharField(max_length=80, blank=True)
    passport_country = models.CharField(max_length=2, blank=True)
    document_type = models.CharField(max_length=32, blank=True)
    document_expires_on = models.DateField(null=True, blank=True)
    address = models.TextField(blank=True)
    city = models.CharField(max_length=120, blank=True)
    postal_code = models.CharField(max_length=24, blank=True)
    blacklisted = models.BooleanField(default=False)
    blacklist_reason = models.TextField(blank=True)
    company_name = models.CharField(max_length=180, blank=True)
    tax_number = models.CharField(max_length=80, blank=True)
    vip = models.BooleanField(default=False)
    gdpr_confirmed = models.BooleanField(default=False)
    email_confirmed = models.BooleanField(default=False)
    phone_confirmed = models.BooleanField(default=False)
    preferences = models.JSONField(default=list, blank=True)
    allergens = models.JSONField(default=list, blank=True)
    loyalty_code = models.CharField(max_length=80, blank=True)
    updated_at = models.DateTimeField(auto_now=True)


class LoyaltyTier(models.Model):
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="loyalty_tiers")
    code = models.SlugField(max_length=80)
    name = models.CharField(max_length=120)
    minimum_points = models.PositiveIntegerField(default=0)
    discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["property", "minimum_points"]
        constraints = [models.UniqueConstraint(fields=["property", "code"], name="unique_loyalty_tier_code_per_property")]


class LoyaltyPolicy(models.Model):
    """Configurable earning, redemption and discount policy for a loyalty tier."""

    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="loyalty_policies")
    tier = models.ForeignKey(LoyaltyTier, on_delete=models.CASCADE, related_name="policies")
    pos_discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    reservation_discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    points_per_currency = models.DecimalField(max_digits=8, decimal_places=4, default=1)
    points_redemption_value = models.DecimalField(max_digits=12, decimal_places=4, default=0)
    valid_from = models.DateField(null=True, blank=True)
    valid_until = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["property", "tier"], name="unique_loyalty_policy_per_tier")]


class VipDefinition(models.Model):
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="vip_definitions")
    code = models.SlugField(max_length=80)
    name = models.CharField(max_length=120)
    benefits = models.JSONField(default=list, blank=True)
    discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    welcome_message = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["property", "code"], name="unique_vip_definition_code")]


class GuestLoyaltyAccount(models.Model):
    guest = models.OneToOneField(Guest, on_delete=models.CASCADE, related_name="loyalty_account")
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="loyalty_accounts")
    tier = models.ForeignKey(LoyaltyTier, on_delete=models.SET_NULL, null=True, blank=True, related_name="accounts")
    membership_number = models.CharField(max_length=80, unique=True)
    points_balance = models.PositiveIntegerField(default=0)
    joined_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["guest", "property"], name="unique_guest_loyalty_property")]

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.guest_id and self.property_id and self.guest.property_id != self.property_id:
            raise ValidationError({"guest": _("Guest must belong to the same property.")})
        if self.tier_id and self.tier.property_id != self.property_id:
            raise ValidationError({"tier": _("Loyalty tier must belong to the same property.")})


class LoyaltyTransaction(models.Model):
    class Kind(models.TextChoices):
        EARN = "earn", _("Earn")
        REDEEM = "redeem", _("Redeem")
        ADJUST = "adjust", _("Adjustment")

    account = models.ForeignKey(GuestLoyaltyAccount, on_delete=models.CASCADE, related_name="transactions")
    kind = models.CharField(max_length=12, choices=Kind.choices)
    points = models.IntegerField()
    note = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["account", "created_at"])]


class GuestSegment(models.Model):
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="guest_segments")
    name = models.CharField(max_length=160)
    description = models.TextField(blank=True)
    criteria = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["property", "name"]
        constraints = [models.UniqueConstraint(fields=["property", "name"], name="unique_guest_segment_name")]


class MessageTemplate(models.Model):
    class Channel(models.TextChoices):
        EMAIL = "email", _("Email")
        SMS = "sms", _("SMS")
        WHATSAPP = "whatsapp", _("WhatsApp")

    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="message_templates")
    code = models.SlugField(max_length=100)
    name = models.CharField(max_length=160)
    channel = models.CharField(max_length=12, choices=Channel.choices)
    subject = models.CharField(max_length=180, blank=True)
    body = models.TextField()
    language = models.CharField(max_length=12, default="tr")
    provider_template_id = models.CharField(max_length=160, blank=True)
    approval_status = models.CharField(max_length=20, default="not_required")
    variables = models.JSONField(default=list, blank=True)
    version = models.PositiveIntegerField(default=1)
    is_active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["property", "channel", "name"]
        constraints = [models.UniqueConstraint(fields=["property", "code"], name="unique_message_template_code")]


class MarketingCampaign(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        SCHEDULED = "scheduled", _("Scheduled")
        SENT = "sent", _("Sent")
        CANCELLED = "cancelled", _("Cancelled")

    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="marketing_campaigns")
    name = models.CharField(max_length=180)
    segment = models.ForeignKey(GuestSegment, on_delete=models.SET_NULL, null=True, blank=True, related_name="campaigns")
    template = models.ForeignKey(MessageTemplate, on_delete=models.SET_NULL, null=True, blank=True, related_name="campaigns")
    status = models.CharField(max_length=14, choices=Status.choices, default=Status.DRAFT)
    scheduled_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class MarketingDelivery(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued", _("Queued")
        SENT = "sent", _("Sent")
        FAILED = "failed", _("Failed")

    campaign = models.ForeignKey(MarketingCampaign, on_delete=models.CASCADE, related_name="deliveries")
    guest = models.ForeignKey(Guest, on_delete=models.CASCADE, related_name="marketing_deliveries")
    channel = models.CharField(max_length=12, choices=MessageTemplate.Channel.choices)
    recipient = models.CharField(max_length=255)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.QUEUED)
    provider_message_id = models.CharField(max_length=180, blank=True)
    error = models.TextField(blank=True)
    queued_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-queued_at"]
        constraints = [models.UniqueConstraint(fields=["campaign", "guest"], name="unique_marketing_delivery_guest")]


class OnlineBookingSettings(models.Model):
    class PaymentProvider(models.TextChoices):
        MANUAL = "manual", _("Manual / hotel payment")
        STRIPE = "stripe", _("Stripe")
        PAYPAL = "paypal", _("PayPal")

    property = models.OneToOneField(Property, on_delete=models.CASCADE, related_name="online_booking_settings")
    booking_page_active = models.BooleanField(default=True)
    online_checkin_active = models.BooleanField(default=False)
    online_payment_active = models.BooleanField(default=False)
    deposit_payment_active = models.BooleanField(default=False)
    extra_services_active = models.BooleanField(default=False)
    room_upgrade_active = models.BooleanField(default=False)
    late_checkout_active = models.BooleanField(default=False)
    transfer_active = models.BooleanField(default=False)
    guest_portal_active = models.BooleanField(default=False)
    payment_provider = models.CharField(max_length=16, choices=PaymentProvider.choices, default=PaymentProvider.MANUAL)
    payment_public_key = models.CharField(max_length=255, blank=True)
    deposit_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    payment_due_hours = models.PositiveIntegerField(default=24)
    seo_title = models.CharField(max_length=180, blank=True)
    seo_description = models.TextField(blank=True)
    meta_keywords = models.CharField(max_length=255, blank=True)
    canonical_url = models.URLField(blank=True)
    og_title = models.CharField(max_length=180, blank=True)
    og_image_url = models.URLField(blank=True)
    google_analytics_id = models.CharField(max_length=80, blank=True)
    google_tag_manager_id = models.CharField(max_length=80, blank=True)
    google_maps_cid = models.CharField(max_length=120, blank=True)
    domain = models.CharField(max_length=255, blank=True)
    facebook_url = models.URLField(blank=True)
    instagram_url = models.URLField(blank=True)
    whatsapp_url = models.URLField(blank=True)
    google_business_url = models.URLField(blank=True)
    online_ratecode = models.CharField(max_length=120, blank=True)
    ical_sync_active = models.BooleanField(default=False)
    ical_feed_url = models.URLField(max_length=1000, blank=True)
    booking_page_version = models.PositiveIntegerField(default=1)
    booking_page_published_at = models.DateTimeField(null=True, blank=True)
    booking_page_publish_status = models.CharField(max_length=20, default="draft")
    show_room_types = models.BooleanField(default=True)
    show_room_prices = models.BooleanField(default=True)
    show_services = models.BooleanField(default=True)
    show_gallery = models.BooleanField(default=True)
    show_reviews = models.BooleanField(default=False)
    allow_multiple_rooms = models.BooleanField(default=True)
    online_checkin_requires_document = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)


class PropertyService(models.Model):
    class Kind(models.TextChoices):
        EXTRA = "extra", _("Extra service")
        LATE_CHECKOUT = "late_checkout", _("Late checkout")
        TRANSFER = "transfer", _("Transfer")
        ROOM_UPGRADE = "room_upgrade", _("Room upgrade")

    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="online_services")
    code = models.SlugField(max_length=80)
    name = models.CharField(max_length=160)
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.EXTRA)
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    currency = models.CharField(max_length=3, default="TRY")
    is_active = models.BooleanField(default=True)
    show_online = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["property", "kind", "name"]
        constraints = [models.UniqueConstraint(fields=["property", "code"], name="unique_property_service_code")]


class ServiceRequest(models.Model):
    class Status(models.TextChoices):
        REQUESTED = "requested", _("Requested")
        CONFIRMED = "confirmed", _("Confirmed")
        REJECTED = "rejected", _("Rejected")
        COMPLETED = "completed", _("Completed")

    reservation = models.ForeignKey(Reservation, on_delete=models.CASCADE, related_name="service_requests")
    service = models.ForeignKey(PropertyService, on_delete=models.PROTECT, related_name="requests")
    quantity = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.REQUESTED)
    scheduled_at = models.DateTimeField(null=True, blank=True)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]


class AccessPermission(models.Model):
    code = models.SlugField(max_length=120, unique=True)
    name = models.CharField(max_length=180)
    module = models.CharField(max_length=80)
    action = models.CharField(max_length=40)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["module", "code"]

    def __str__(self):
        return f"{self.module} · {self.action}"


class PropertyRole(models.Model):
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="access_roles")
    name = models.CharField(max_length=120)
    department = models.CharField(max_length=120, blank=True)
    permissions = models.ManyToManyField(AccessPermission, blank=True, related_name="roles")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["property", "name"]
        constraints = [models.UniqueConstraint(fields=["property", "name"], name="unique_property_role_name")]

    def __str__(self):
        return f"{self.property.name} · {self.name}"


class UserPropertyAccess(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="property_accesses")
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="user_accesses")
    role = models.ForeignKey(PropertyRole, on_delete=models.PROTECT, related_name="user_accesses")
    is_active = models.BooleanField(default=True)
    valid_from = models.DateField(null=True, blank=True)
    valid_until = models.DateField(null=True, blank=True)
    allowed_from_time = models.TimeField(null=True, blank=True)
    allowed_until_time = models.TimeField(null=True, blank=True)
    two_factor_required = models.BooleanField(default=False)
    last_pin_change = models.DateTimeField(null=True, blank=True)
    allowed_ip = models.GenericIPAddressField(null=True, blank=True)
    device_label = models.CharField(max_length=120, blank=True)
    pin_hash = models.CharField(max_length=128, blank=True)
    purchase_approval_required = models.BooleanField(default=False)
    bypass_price_control = models.BooleanField(default=False)
    own_cash_only = models.BooleanField(default=False)
    pos_access = models.BooleanField(default=False)
    financial_access = models.BooleanField(default=False)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "property", "role"], name="unique_user_property_role")]

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.role_id and self.property_id and self.role.property_id != self.property_id:
            raise ValidationError({"role": _("Role must belong to the selected property.")})
        if self.valid_from and self.valid_until and self.valid_until < self.valid_from:
            raise ValidationError({"valid_until": _("Validity end cannot be before start.")})
        if bool(self.allowed_from_time) != bool(self.allowed_until_time):
            raise ValidationError({"allowed_from_time": _("Both access times must be provided together.")})


class UserAccessLog(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="access_logs")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="access_actions")
    property = models.ForeignKey(Property, on_delete=models.SET_NULL, null=True, blank=True, related_name="access_logs")
    successful = models.BooleanField(default=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=500, blank=True)
    event = models.CharField(max_length=80, default="login")
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["property", "created_at"]), models.Index(fields=["user", "created_at"])]


class SupportTicket(models.Model):
    class Priority(models.TextChoices):
        LOW = "low", _("Düşük")
        NORMAL = "normal", _("Normal")
        HIGH = "high", _("Yüksek")
        URGENT = "urgent", _("Acil")

    class Status(models.TextChoices):
        NEW = "new", _("Yeni")
        OPEN = "open", _("Açık")
        PENDING_USER = "pending_user", _("Kullanıcı yanıtı bekleniyor")
        PENDING_STAFF = "pending_staff", _("Destek yanıtı bekleniyor")
        ON_HOLD = "on_hold", _("Beklemede")
        RESOLVED = "resolved", _("Çözüldü")
        CLOSED = "closed", _("Kapatıldı")

    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="support_tickets")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="support_tickets")
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="assigned_support_tickets")
    module = models.CharField(max_length=80, default="general")
    subject = models.CharField(max_length=180)
    message = models.TextField()
    attachment = models.FileField(upload_to="support/%Y/%m/", blank=True)
    priority = models.CharField(max_length=12, choices=Priority.choices, default=Priority.NORMAL)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NEW, db_index=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["property", "status", "created_at"])]


class SupportTicketMessage(models.Model):
    ticket = models.ForeignKey(SupportTicket, on_delete=models.CASCADE, related_name="messages")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    body = models.TextField()
    is_internal = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]


class SupportAuditEvent(models.Model):
    ticket = models.ForeignKey(SupportTicket, on_delete=models.CASCADE, related_name="audit_events")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    event = models.CharField(max_length=80)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class SupportFAQCategory(models.Model):
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="support_faq_categories")
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["order", "name"]
        constraints = [models.UniqueConstraint(fields=["property", "name"], name="unique_support_faq_category")]


class SupportFAQItem(models.Model):
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="support_faq_items")
    category = models.ForeignKey(SupportFAQCategory, on_delete=models.CASCADE, related_name="items")
    question = models.CharField(max_length=500)
    answer = models.TextField()
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    is_featured = models.BooleanField(default=False)
    view_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["category__order", "order", "question"]


class SupportHelpLink(models.Model):
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="support_help_links")
    name = models.CharField(max_length=150)
    url = models.URLField(blank=True)
    phone_number = models.CharField(max_length=40, blank=True)
    link_type = models.CharField(max_length=30, default="guide")
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["order", "name"]


class SupportVideoCategory(models.Model):
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="support_video_categories")
    name = models.CharField(max_length=150)
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)


class SupportVideo(models.Model):
    category = models.ForeignKey(SupportVideoCategory, on_delete=models.CASCADE, related_name="videos")
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    youtube_video_id = models.CharField(max_length=50)
    duration_display = models.CharField(max_length=20, blank=True)
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    @property
    def embed_url(self):
        return f"https://www.youtube-nocookie.com/embed/{self.youtube_video_id.strip()}"


class SupportEducationRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", _("İnceleniyor")
        APPROVED = "approved", _("Onaylandı")
        IN_PROGRESS = "in_progress", _("Devam ediyor")
        COMPLETED = "completed", _("Tamamlandı")
        CANCELLED = "cancelled", _("İptal edildi")

    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="support_education_requests")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="support_education_requests")
    topic = models.CharField(max_length=120)
    description = models.TextField()
    priority = models.CharField(max_length=10, choices=SupportTicket.Priority.choices, default=SupportTicket.Priority.NORMAL)
    contact_preference = models.CharField(max_length=20, default="email")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="assigned_education_requests")
    internal_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class SupportReferral(models.Model):
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="support_referrals")
    referrer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="support_referrals")
    business_name = models.CharField(max_length=200)
    contact_name = models.CharField(max_length=200)
    contact_email = models.EmailField()
    contact_phone = models.CharField(max_length=40)
    message = models.TextField(blank=True)
    status = models.CharField(max_length=20, default="pending")
    created_at = models.DateTimeField(auto_now_add=True)


class FrontOfficeCallRequest(models.Model):
    class Status(models.TextChoices):
        NEW = "new", _("Yeni")
        CONTACTED = "contacted", _("Geri dönüş yapıldı")
        CONVERTED = "converted", _("Rezervasyona dönüştü")
        CLOSED = "closed", _("Kapatıldı")

    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="front_office_call_requests")
    guest = models.ForeignKey(Guest, on_delete=models.SET_NULL, null=True, blank=True, related_name="call_requests")
    reservation = models.ForeignKey(Reservation, on_delete=models.SET_NULL, null=True, blank=True, related_name="call_requests")
    name = models.CharField(max_length=160)
    phone = models.CharField(max_length=40, blank=True)
    email = models.EmailField(blank=True)
    note = models.TextField(blank=True)
    callback_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.NEW, db_index=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="created_call_requests")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]


class FrontCashTransaction(models.Model):
    class TransactionType(models.TextChoices):
        RECEIPT = "receipt", _("Receipt")
        PAYMENT = "payment", _("Payment")
        REFUND = "refund", _("Refund")
        ADJUSTMENT = "adjustment", _("Adjustment")

    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="front_cash_transactions")
    reservation = models.ForeignKey(Reservation, on_delete=models.SET_NULL, null=True, blank=True, related_name="front_cash_transactions")
    guest = models.ForeignKey(Guest, on_delete=models.SET_NULL, null=True, blank=True, related_name="front_cash_transactions")
    transaction_type = models.CharField(max_length=16, choices=TransactionType.choices)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default="TRY")
    reference = models.CharField(max_length=120, blank=True)
    description = models.CharField(max_length=255, blank=True)
    posted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="front_cash_transactions")
    posted_at = models.DateTimeField(auto_now_add=True)
    is_voided = models.BooleanField(default=False)

    class Meta:
        ordering = ["-posted_at"]
        indexes = [models.Index(fields=["property", "posted_at"]), models.Index(fields=["property", "transaction_type"])]


class CashierShift(models.Model):
    """Front-cash shift opening, closing and reconciliation record."""

    class Status(models.TextChoices):
        OPEN = "open", _("Open")
        CLOSED = "closed", _("Closed")
        RECONCILIATION = "reconciliation", _("Reconciliation")

    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="cashier_shifts")
    cashier = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="cashier_shifts")
    opened_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    opening_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    expected_closing_balance = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    closing_balance = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    cash_total = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    card_total = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    bank_transfer_total = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    other_payment_total = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    variance = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    currency = models.CharField(max_length=3, default="TRY")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    closing_note = models.TextField(blank=True)
    closed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="closed_cashier_shifts")

    class Meta:
        ordering = ["-opened_at"]
        indexes = [models.Index(fields=["property", "status", "opened_at"])]


class CreditAccount(models.Model):
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="credit_accounts")
    code = models.SlugField(max_length=80)
    name = models.CharField(max_length=180)
    tax_number = models.CharField(max_length=80, blank=True)
    credit_limit = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    currency = models.CharField(max_length=3, default="TRY")
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["property", "code"], name="unique_credit_account_code")]


class FolioRoutingRule(models.Model):
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="folio_routing_rules")
    name = models.CharField(max_length=160)
    source_department = models.CharField(max_length=120)
    target_folio = models.CharField(max_length=80, default="guest")
    revenue_code = models.CharField(max_length=80, blank=True)
    is_active = models.BooleanField(default=True)
    priority = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["priority", "name"]


class GuestMedicalDailyRecord(models.Model):
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="guest_medical_daily_records")
    guest = models.ForeignKey(Guest, on_delete=models.PROTECT, related_name="medical_daily_records")
    reservation = models.ForeignKey(Reservation, on_delete=models.SET_NULL, null=True, blank=True, related_name="medical_daily_records")
    record_date = models.DateField()
    note = models.TextField()
    restricted = models.BooleanField(default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="created_medical_daily_records")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-record_date", "-created_at"]


class LostAndFoundItem(models.Model):
    class Status(models.TextChoices):
        STORED = "stored", _("Stored")
        CLAIMED = "claimed", _("Claimed")
        DISPOSED = "disposed", _("Disposed")

    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="lost_and_found_items")
    unit = models.ForeignKey(Unit, on_delete=models.SET_NULL, null=True, blank=True, related_name="lost_and_found_items")
    guest = models.ForeignKey(Guest, on_delete=models.SET_NULL, null=True, blank=True, related_name="lost_and_found_items")
    description = models.CharField(max_length=255)
    found_location = models.CharField(max_length=160, blank=True)
    found_at = models.DateTimeField()
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.STORED)
    storage_reference = models.CharField(max_length=120, blank=True)
    claimant_name = models.CharField(max_length=160, blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="created_lost_and_found_items")


class HotelPhoneBookEntry(models.Model):
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="phone_book_entries")
    name = models.CharField(max_length=160)
    department = models.CharField(max_length=120, blank=True)
    phone = models.CharField(max_length=40)
    extension = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)


class ParkEntry(models.Model):
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="park_entries")
    plate_number = models.CharField(max_length=32)
    guest = models.ForeignKey(Guest, on_delete=models.SET_NULL, null=True, blank=True, related_name="park_entries")
    reservation = models.ForeignKey(Reservation, on_delete=models.SET_NULL, null=True, blank=True, related_name="park_entries")
    entry_at = models.DateTimeField()
    exit_at = models.DateTimeField(null=True, blank=True)
    parking_space = models.CharField(max_length=40, blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="created_park_entries")


class DepartmentDefinition(models.Model):
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="department_definitions")
    code = models.SlugField(max_length=40)
    name = models.CharField(max_length=120)
    department_type = models.CharField(max_length=80, blank=True)
    default_revenue_code = models.CharField(max_length=40, blank=True)
    vat_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    pos_printer = models.CharField(max_length=120, blank=True)
    accounting_account = models.CharField(max_length=80, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]
        constraints = [models.UniqueConstraint(fields=["property", "code"], name="unique_department_definition_code")]


class RevenueCode(models.Model):
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="revenue_codes")
    code = models.SlugField(max_length=40)
    name = models.CharField(max_length=120)
    vat_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]
        constraints = [models.UniqueConstraint(fields=["property", "code"], name="unique_revenue_code")]


class CurrencyDefinition(models.Model):
    class Role(models.TextChoices):
        BASE = "base", _("Base currency")
        OTA = "ota", _("OTA/sales currency")
        SECONDARY = "secondary", _("Secondary currency")

    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="currency_definitions")
    code = models.CharField(max_length=3)
    name = models.CharField(max_length=80)
    symbol = models.CharField(max_length=8, blank=True)
    decimal_places = models.PositiveSmallIntegerField(default=2)
    role = models.CharField(max_length=12, choices=Role.choices, default=Role.SECONDARY)
    is_base = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["property", "code"]
        constraints = [models.UniqueConstraint(fields=["property", "code"], name="unique_currency_definition_code")]


class DailyCurrencyRate(models.Model):
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="daily_currency_rates")
    rate_date = models.DateField()
    from_currency = models.CharField(max_length=3)
    to_currency = models.CharField(max_length=3)
    rate = models.DecimalField(max_digits=16, decimal_places=8)
    buy_rate = models.DecimalField(max_digits=16, decimal_places=8, null=True, blank=True)
    sell_rate = models.DecimalField(max_digits=16, decimal_places=8, null=True, blank=True)
    source = models.CharField(max_length=80, blank=True)
    source_reference = models.CharField(max_length=180, blank=True)
    valid_from = models.DateTimeField(null=True, blank=True)
    valid_until = models.DateTimeField(null=True, blank=True)
    is_manual = models.BooleanField(default=False)
    synced_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-rate_date", "from_currency", "to_currency"]
        constraints = [models.UniqueConstraint(fields=["property", "rate_date", "from_currency", "to_currency"], name="unique_daily_currency_rate")]


class BankAccount(models.Model):
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="bank_accounts")
    name = models.CharField(max_length=160)
    bank_name = models.CharField(max_length=160, blank=True)
    account_number = models.CharField(max_length=80, blank=True)
    iban = models.CharField(max_length=80, blank=True)
    swift = models.CharField(max_length=40, blank=True)
    currency = models.CharField(max_length=3, default="TRY")
    is_active = models.BooleanField(default=True)
    secret_ref = models.CharField(max_length=180, blank=True, help_text="Secret manager reference for protected banking data.")


class NotificationDefinition(models.Model):
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="notification_definitions")
    code = models.SlugField(max_length=100)
    name = models.CharField(max_length=160)
    event = models.CharField(max_length=100)
    channel = models.CharField(max_length=20, default="email")
    subject = models.CharField(max_length=180, blank=True)
    body = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["property", "code"], name="unique_notification_definition_code")]


class ApiKeyDefinition(models.Model):
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="api_key_definitions")
    name = models.CharField(max_length=160)
    provider = models.CharField(max_length=80)
    key_hash = models.CharField(max_length=128)
    secret_ref = models.CharField(max_length=180, blank=True, help_text="Secret manager reference; never store the raw API key.")
    last_used_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)


class EcrDevice(models.Model):
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="ecr_devices")
    name = models.CharField(max_length=160)
    model = models.CharField(max_length=120, blank=True)
    terminal_id = models.CharField(max_length=120, blank=True)
    revenue_group_mapping = models.JSONField(default=dict, blank=True)
    vat_mapping = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)


class StandardCharge(models.Model):
    class ChargeType(models.TextChoices):
        PACKAGE = "package", _("Package")
        TAX = "tax", _("Tax")
        RENTABLE = "rentable", _("Rentable")
        BOARD = "board", _("Board")

    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="standard_charges")
    code = models.SlugField(max_length=80)
    name = models.CharField(max_length=160)
    charge_type = models.CharField(max_length=16, choices=ChargeType.choices)
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    currency = models.CharField(max_length=3, default="TRY")
    vat_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["property", "code"], name="unique_standard_charge_code")]


class Invoice(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        ISSUED = "issued", _("Issued")
        PAID = "paid", _("Paid")
        CANCELLED = "cancelled", _("Cancelled")

    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="invoices")
    reservation = models.ForeignKey(Reservation, on_delete=models.PROTECT, null=True, blank=True, related_name="invoices")
    number = models.CharField(max_length=40)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    issue_date = models.DateField()
    due_date = models.DateField(null=True, blank=True)
    currency = models.CharField(max_length=3, default="TRY")
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tax = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    customer_name = models.CharField(max_length=180)
    customer_tax_number = models.CharField(max_length=40, blank=True)
    notes = models.TextField(blank=True)
    lines = models.JSONField(default=list, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_invoices")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-issue_date", "-id"]
        constraints = [models.UniqueConstraint(fields=["property", "number"], name="unique_invoice_number_per_property")]


class PaymentGateway(models.Model):
    class Provider(models.TextChoices):
        STRIPE = "stripe", _("Stripe")
        PAYPAL = "paypal", _("PayPal")
        NESTPAY_HALKBANK = "nestpay_halkbank", _("Halkbank / Asseco NestPay 3D Secure")
        CPAY_STB = "cpay_stb", _("cPay / STB")

    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="payment_gateways")
    bank_name = models.CharField(max_length=160)
    payment_model = models.CharField(max_length=80, choices=Provider.choices, blank=True)
    client_no = models.CharField(max_length=80, blank=True)
    account_name = models.CharField(max_length=160, blank=True)
    pos_name = models.CharField(max_length=120, blank=True)
    currency = models.CharField(max_length=3, default="TRY")
    active = models.BooleanField(default=True)
    default_gate = models.BooleanField(default=False)
    credential_ref = models.CharField(max_length=180, blank=True, help_text="Secret manager reference; never store passwords here.")
    merchant_id = models.CharField(max_length=120, blank=True)
    terminal_id = models.CharField(max_length=120, blank=True)
    api_username_ref = models.CharField(max_length=180, blank=True, help_text="Secret manager reference; never store credentials here.")
    endpoint_url = models.URLField(max_length=500, blank=True)
    environment = models.CharField(max_length=16, default="sandbox")
    supports_3ds = models.BooleanField(default=True)
    configuration = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)


class NightAuditRun(models.Model):
    class Status(models.TextChoices):
        STARTED = "started", _("Started")
        COMPLETED = "completed", _("Completed")
        FAILED = "failed", _("Failed")

    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="night_audit_runs")
    audit_date = models.DateField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.STARTED)
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="night_audit_runs")
    summary = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)


class NightAuditLog(models.Model):
    """Auditable event/error row produced during a night-audit run."""

    class Level(models.TextChoices):
        INFO = "info", _("Info")
        WARNING = "warning", _("Warning")
        ERROR = "error", _("Error")

    run = models.ForeignKey(NightAuditRun, on_delete=models.CASCADE, related_name="logs")
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="night_audit_logs")
    level = models.CharField(max_length=12, choices=Level.choices, default=Level.INFO)
    event_code = models.CharField(max_length=80, blank=True)
    message = models.TextField()
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="night_audit_logs")
    occurred_at = models.DateTimeField(auto_now_add=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-occurred_at"]
        indexes = [models.Index(fields=["property", "occurred_at"]), models.Index(fields=["run", "level"])]


class Agency(models.Model):
    class PaymentMethod(models.TextChoices):
        INVOICE = "invoice", _("Invoice")
        CARD = "card", _("Card")
        PREPAID = "prepaid", _("Prepaid")

    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="agencies")
    code = models.SlugField(max_length=60)
    name = models.CharField(max_length=180)
    contact_name = models.CharField(max_length=160, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=40, blank=True)
    commission_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    contract_number = models.CharField(max_length=80, blank=True)
    contract_start = models.DateField(null=True, blank=True)
    contract_end = models.DateField(null=True, blank=True)
    commission_currency = models.CharField(max_length=3, default="TRY")
    rate_notes = models.TextField(blank=True)
    payment_method = models.CharField(max_length=16, choices=PaymentMethod.choices, default=PaymentMethod.INVOICE)
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["property", "code"], name="unique_agency_code_per_property")]


class AgencyRateAgreement(models.Model):
    """Contracted rate and commission terms for one travel agency."""

    agency = models.ForeignKey(Agency, on_delete=models.CASCADE, related_name="rate_agreements")
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="agency_rate_agreements")
    unit_type = models.ForeignKey(UnitType, on_delete=models.SET_NULL, null=True, blank=True, related_name="agency_agreements")
    rate_plan = models.ForeignKey(RatePlan, on_delete=models.SET_NULL, null=True, blank=True, related_name="agency_agreements")
    name = models.CharField(max_length=160)
    valid_from = models.DateField(null=True, blank=True)
    valid_until = models.DateField(null=True, blank=True)
    commission_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    currency = models.CharField(max_length=3, default="TRY")
    allotment_units = models.PositiveIntegerField(default=0)
    release_hours = models.PositiveIntegerField(default=0)
    contracted_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    terms = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["agency", "name"]
        constraints = [models.UniqueConstraint(fields=["agency", "name"], name="unique_agency_rate_agreement")]


class AgencyCommissionRecord(models.Model):
    """Auditable commission calculation linked to an agency booking."""

    agency = models.ForeignKey(Agency, on_delete=models.CASCADE, related_name="commission_records")
    reservation = models.ForeignKey(Reservation, on_delete=models.SET_NULL, null=True, blank=True, related_name="agency_commission_records")
    agreement = models.ForeignKey(AgencyRateAgreement, on_delete=models.SET_NULL, null=True, blank=True, related_name="commission_records")
    gross_amount = models.DecimalField(max_digits=12, decimal_places=2)
    commission_amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default="TRY")
    recorded_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)


class ParkingLot(models.Model):
    """A bookable parking facility belonging to one hotel property."""

    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="parking_lots")
    code = models.SlugField(max_length=60)
    name = models.CharField(max_length=160)
    location = models.CharField(max_length=240, blank=True)
    capacity = models.PositiveIntegerField(default=0)
    hourly_rate = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    daily_rate = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    daily_max_rate = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    night_rate = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    night_start = models.TimeField(null=True, blank=True)
    night_end = models.TimeField(null=True, blank=True)
    anpr_enabled = models.BooleanField(default=False)
    map_reference = models.CharField(max_length=180, blank=True)
    currency = models.CharField(max_length=3, default="TRY")
    opening_time = models.TimeField(null=True, blank=True)
    closing_time = models.TimeField(null=True, blank=True)
    grace_minutes = models.PositiveIntegerField(default=30)
    booking_enabled = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["property", "name"]
        constraints = [models.UniqueConstraint(fields=["property", "code"], name="unique_parking_lot_code_per_property")]


class ParkingSpace(models.Model):
    class SpaceType(models.TextChoices):
        STANDARD = "standard", _("Standard")
        COVERED = "covered", _("Covered")
        ACCESSIBLE = "accessible", _("Accessible")
        EV = "ev", _("EV charging")

    class Status(models.TextChoices):
        AVAILABLE = "available", _("Available")
        MAINTENANCE = "maintenance", _("Maintenance")
        BLOCKED = "blocked", _("Blocked")

    parking_lot = models.ForeignKey(ParkingLot, on_delete=models.CASCADE, related_name="spaces")
    code = models.CharField(max_length=60)
    space_type = models.CharField(max_length=16, choices=SpaceType.choices, default=SpaceType.STANDARD)
    floor = models.CharField(max_length=80, blank=True)
    zone = models.CharField(max_length=80, blank=True)
    is_covered = models.BooleanField(default=False)
    has_ev_charger = models.BooleanField(default=False)
    is_accessible = models.BooleanField(default=False)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.AVAILABLE)
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["parking_lot", "code"]
        constraints = [models.UniqueConstraint(fields=["parking_lot", "code"], name="unique_parking_space_code_per_lot")]


class VehicleRentalRate(models.Model):
    vehicle = models.ForeignKey(Vehicle, on_delete=models.CASCADE, related_name="rental_rates")
    name = models.CharField(max_length=160)
    valid_from = models.DateField(null=True, blank=True)
    valid_until = models.DateField(null=True, blank=True)
    daily_rate = models.DecimalField(max_digits=12, decimal_places=2)
    weekly_rate = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    monthly_rate = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    early_booking_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    last_minute_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    service_fee = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    airport_fee = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    pickup_fee = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    dropoff_fee = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    vat_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    special_consumption_tax_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    preauthorization_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    cancellation_free_hours = models.PositiveIntegerField(default=0)
    cancellation_fee_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    channel_code = models.CharField(max_length=80, blank=True)
    deposit_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    included_km_per_day = models.PositiveIntegerField(default=0)
    extra_km_rate = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    minimum_driver_age = models.PositiveSmallIntegerField(default=21)
    currency = models.CharField(max_length=3, default="TRY")
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["vehicle", "name"]


class RentalPricingRule(models.Model):
    class RuleType(models.TextChoices):
        SEASON = "season", _("Season")
        PROMO = "promo", _("Promotion")
        CHANNEL = "channel", _("Channel")

    class AdjustmentType(models.TextChoices):
        PERCENT = "percent", _("Percent")
        FIXED = "fixed", _("Fixed amount")

    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="rental_pricing_rules")
    name = models.CharField(max_length=160)
    code = models.SlugField(max_length=80)
    rule_type = models.CharField(max_length=16, choices=RuleType.choices, default=RuleType.SEASON)
    valid_from = models.DateField(null=True, blank=True)
    valid_until = models.DateField(null=True, blank=True)
    vehicle_class = models.CharField(max_length=80, blank=True)
    channel_code = models.CharField(max_length=80, blank=True)
    promo_code = models.CharField(max_length=80, blank=True)
    corporate_code = models.CharField(max_length=80, blank=True)
    loyalty_code = models.CharField(max_length=80, blank=True)
    minimum_days = models.PositiveSmallIntegerField(default=1)
    maximum_days = models.PositiveSmallIntegerField(null=True, blank=True)
    adjustment_type = models.CharField(max_length=12, choices=AdjustmentType.choices, default=AdjustmentType.PERCENT)
    adjustment_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    priority = models.PositiveSmallIntegerField(default=100)
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["property", "priority", "name"]
        constraints = [models.UniqueConstraint(fields=["property", "code"], name="unique_rental_pricing_rule_code")]


class ParkingReservation(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        CONFIRMED = "confirmed", _("Confirmed")
        CHECKED_IN = "checked_in", _("Checked in")
        CHECKED_OUT = "checked_out", _("Checked out")
        CANCELLED = "cancelled", _("Cancelled")
        NO_SHOW = "no_show", _("No-show")

    class Source(models.TextChoices):
        DIRECT = "direct", _("Direct")
        ONLINE = "online", _("Online")
        ADMIN = "admin", _("Admin")
        PHONE = "phone", _("Phone")

    class PaymentStatus(models.TextChoices):
        UNPAID = "unpaid", _("Unpaid")
        AUTHORIZED = "authorized", _("Authorized")
        PAID = "paid", _("Paid")
        REFUNDED = "refunded", _("Refunded")

    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="parking_reservations")
    parking_lot = models.ForeignKey(ParkingLot, on_delete=models.PROTECT, related_name="reservations")
    parking_space = models.ForeignKey(ParkingSpace, on_delete=models.PROTECT, null=True, blank=True, related_name="reservations")
    guest = models.ForeignKey(Guest, on_delete=models.SET_NULL, null=True, blank=True, related_name="parking_reservations")
    reservation = models.ForeignKey(Reservation, on_delete=models.SET_NULL, null=True, blank=True, related_name="parking_reservations")
    confirmation_code = models.CharField(max_length=24, unique=True, blank=True)
    customer_name = models.CharField(max_length=180)
    customer_email = models.EmailField(blank=True)
    customer_phone = models.CharField(max_length=40, blank=True)
    vehicle_plate = models.CharField(max_length=32, blank=True)
    start_at = models.DateTimeField()
    end_at = models.DateTimeField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    source = models.CharField(max_length=12, choices=Source.choices, default=Source.DIRECT)
    payment_status = models.CharField(max_length=16, choices=PaymentStatus.choices, default=PaymentStatus.UNPAID)
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    currency = models.CharField(max_length=3, default="TRY")
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_parking_reservations")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-start_at", "-created_at"]
        indexes = [models.Index(fields=["property", "start_at"]), models.Index(fields=["parking_lot", "status"])]

    def clean(self):
        errors = {}
        if self.end_at and self.start_at and self.end_at <= self.start_at:
            errors["end_at"] = _("Bitiş zamanı başlangıçtan sonra olmalıdır.")
        if self.parking_lot_id and self.property_id and self.parking_lot.property_id != self.property_id:
            errors["parking_lot"] = _("Otopark seçili tesise ait olmalıdır.")
        if self.parking_space_id and self.parking_space.parking_lot_id != self.parking_lot_id:
            errors["parking_space"] = _("Park yeri seçilen otoparka ait olmalıdır.")
        if not errors and self.parking_space_id and self.start_at and self.end_at:
            conflict = ParkingReservation.objects.filter(
                parking_space_id=self.parking_space_id,
                start_at__lt=self.end_at,
                end_at__gt=self.start_at,
                status__in=[self.Status.PENDING, self.Status.CONFIRMED, self.Status.CHECKED_IN],
            ).exclude(pk=self.pk).exists()
            if conflict:
                errors["parking_space"] = _("Bu zaman aralığında park yeri başka bir rezervasyona ayrılmıştır.")
        if not errors and not self.parking_space_id and self.parking_lot_id and self.start_at and self.end_at:
            overlapping = ParkingReservation.objects.filter(
                parking_lot_id=self.parking_lot_id,
                start_at__lt=self.end_at,
                end_at__gt=self.start_at,
                status__in=[self.Status.PENDING, self.Status.CONFIRMED, self.Status.CHECKED_IN],
            ).exclude(pk=self.pk).count()
            if self.parking_lot.capacity and overlapping >= self.parking_lot.capacity:
                errors["parking_lot"] = _("Bu zaman aralığında otopark kapasitesi doludur.")
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if not self.confirmation_code:
            self.confirmation_code = f"P-{timezone.now():%y%m%d}-{uuid4().hex[:8].upper()}"
        return super().save(*args, **kwargs)


class VehicleRentalBooking(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        CONFIRMED = "confirmed", _("Confirmed")
        ACTIVE = "active", _("Active")
        COMPLETED = "completed", _("Completed")
        CANCELLED = "cancelled", _("Cancelled")
        NO_SHOW = "no_show", _("No-show")

    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="vehicle_rental_bookings")
    vehicle = models.ForeignKey(Vehicle, on_delete=models.PROTECT, related_name="rental_bookings")
    rental_rate = models.ForeignKey(VehicleRentalRate, on_delete=models.SET_NULL, null=True, blank=True, related_name="bookings")
    guest = models.ForeignKey(Guest, on_delete=models.SET_NULL, null=True, blank=True, related_name="vehicle_rental_bookings")
    driver_profile = models.ForeignKey("RentalDriverProfile", on_delete=models.SET_NULL, null=True, blank=True, related_name="bookings")
    reservation = models.ForeignKey(Reservation, on_delete=models.SET_NULL, null=True, blank=True, related_name="vehicle_rental_bookings")
    confirmation_code = models.CharField(max_length=24, unique=True, blank=True)
    payment_token = models.UUIDField(default=uuid4, unique=True, editable=False)
    public_manage_token = models.UUIDField(default=uuid4, unique=True, editable=False)
    customer_name = models.CharField(max_length=180)
    customer_email = models.EmailField(blank=True)
    customer_phone = models.CharField(max_length=40, blank=True)
    pickup_location = models.CharField(max_length=180, blank=True)
    dropoff_location = models.CharField(max_length=180, blank=True)
    pickup_location_ref = models.ForeignKey("RentalLocation", on_delete=models.SET_NULL, null=True, blank=True, related_name="pickup_bookings")
    dropoff_location_ref = models.ForeignKey("RentalLocation", on_delete=models.SET_NULL, null=True, blank=True, related_name="dropoff_bookings")
    pickup_at = models.DateTimeField()
    dropoff_at = models.DateTimeField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    source = models.CharField(max_length=12, choices=ParkingReservation.Source.choices, default=ParkingReservation.Source.DIRECT)
    daily_rate = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    weekly_rate = models.DecimalField(max_digits=12, decimal_places=2, default=0, blank=True)
    monthly_rate = models.DecimalField(max_digits=12, decimal_places=2, default=0, blank=True)
    service_fee = models.DecimalField(max_digits=12, decimal_places=2, default=0, blank=True)
    airport_fee = models.DecimalField(max_digits=12, decimal_places=2, default=0, blank=True)
    one_way_fee = models.DecimalField(max_digits=12, decimal_places=2, default=0, blank=True)
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0, blank=True)
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0, blank=True)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    deposit_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    currency = models.CharField(max_length=3, default="TRY")
    mileage_start = models.PositiveIntegerField(null=True, blank=True)
    mileage_end = models.PositiveIntegerField(null=True, blank=True)
    driver_age = models.PositiveSmallIntegerField(null=True, blank=True)
    license_number = models.CharField(max_length=80, blank=True, help_text=_("Store only the minimum legally required data."))
    driver_license_country = models.CharField(max_length=2, blank=True)
    license_duration_months = models.PositiveSmallIntegerField(null=True, blank=True)
    additional_driver_count = models.PositiveSmallIntegerField(default=0)
    promo_code = models.CharField(max_length=80, blank=True)
    corporate_code = models.CharField(max_length=80, blank=True)
    loyalty_code = models.CharField(max_length=80, blank=True)
    vehicle_class = models.CharField(max_length=80, blank=True)
    locale = models.CharField(max_length=12, default="tr-TR")
    flight_number = models.CharField(max_length=40, blank=True)
    channel_reference = models.CharField(max_length=160, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    no_show_at = models.DateTimeField(null=True, blank=True)
    insurance_package = models.CharField(max_length=80, blank=True)
    extra_products = models.JSONField(default=list, blank=True)
    payment_method = models.CharField(max_length=32, blank=True)
    prepayment_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    remaining_payment_due = models.DateTimeField(null=True, blank=True)
    cancellation_policy = models.TextField(blank=True)
    cancellation_policy_ref = models.ForeignKey("RentalCancellationPolicy", on_delete=models.SET_NULL, null=True, blank=True, related_name="bookings")
    notes = models.TextField(blank=True)
    privacy_consent_at = models.DateTimeField(null=True, blank=True)
    privacy_policy_version = models.CharField(max_length=40, blank=True)
    data_retention_until = models.DateField(null=True, blank=True)
    marketing_consent = models.BooleanField(default=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_vehicle_rental_bookings")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-pickup_at", "-created_at"]
        indexes = [models.Index(fields=["property", "pickup_at"]), models.Index(fields=["vehicle", "status"])]

    def clean(self):
        errors = {}
        if self.dropoff_at and self.pickup_at and self.dropoff_at <= self.pickup_at:
            errors["dropoff_at"] = _("Teslim zamanı alıştan sonra olmalıdır.")
        if self.vehicle_id and self.property_id and self.vehicle.property_id != self.property_id:
            errors["vehicle"] = _("Araç seçili tesise ait olmalıdır.")
        if self.rental_rate_id and self.rental_rate.vehicle_id != self.vehicle_id:
            errors["rental_rate"] = _("Tarife seçilen araca ait olmalıdır.")
        if self.pickup_location_ref_id and self.pickup_location_ref.property_id != self.property_id:
            errors["pickup_location_ref"] = _("Alış lokasyonu seçili tesise ait olmalıdır.")
        if self.dropoff_location_ref_id and self.dropoff_location_ref.property_id != self.property_id:
            errors["dropoff_location_ref"] = _("İade lokasyonu seçili tesise ait olmalıdır.")
        if self.vehicle_id and self.driver_age is not None and self.driver_age < self.vehicle.minimum_driver_age:
            errors["driver_age"] = _("Sürücü yaşı araç için tanımlanan minimum yaştan küçük olamaz.")
        if self.vehicle_id and self.license_duration_months is not None and self.license_duration_months < self.vehicle.minimum_license_months:
            errors["license_duration_months"] = _("Ehliyet süresi araç için tanımlanan minimum süreden az olamaz.")
        if self.property_id and isinstance(self.extra_products, list):
            invalid_extras = RentalExtraProduct.objects.filter(
                id__in=[value for value in self.extra_products if str(value).isdigit()],
            ).exclude(property_id=self.property_id).exists()
            if invalid_extras:
                errors["extra_products"] = _("Ek ürünler seçili tesise ait olmalıdır.")
        if self.property_id and str(self.insurance_package).isdigit():
            package = RentalInsurancePackage.objects.filter(pk=int(self.insurance_package)).first()
            if package and package.property_id != self.property_id:
                errors["insurance_package"] = _("Sigorta paketi seçili tesise ait olmalıdır.")
        if not errors and self.vehicle_id and self.pickup_at and self.dropoff_at:
            conflict = VehicleRentalBooking.objects.filter(
                vehicle_id=self.vehicle_id,
                pickup_at__lt=self.dropoff_at,
                dropoff_at__gt=self.pickup_at,
                status__in=[self.Status.PENDING, self.Status.CONFIRMED, self.Status.ACTIVE],
            ).exclude(pk=self.pk).exists()
            if conflict:
                errors["vehicle"] = _("Bu zaman aralığında araç başka bir kiralamaya ayrılmıştır.")
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if not self.confirmation_code:
            self.confirmation_code = f"R-{timezone.now():%y%m%d}-{uuid4().hex[:8].upper()}"
        return super().save(*args, **kwargs)


class RentalDriverProfile(models.Model):
    """Property-scoped renter/driver record without storing unnecessary identity data."""

    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="rental_driver_profiles")
    guest = models.ForeignKey(Guest, on_delete=models.SET_NULL, null=True, blank=True, related_name="rental_driver_profiles")
    full_name = models.CharField(max_length=180)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=40, blank=True)
    license_country = models.CharField(max_length=2, blank=True)
    license_number = models.CharField(max_length=80, blank=True)
    license_issued_at = models.DateField(null=True, blank=True)
    license_expires_at = models.DateField(null=True, blank=True)
    identity_document_ref = models.CharField(max_length=180, blank=True)
    license_document = models.FileField(upload_to="rental-driver-documents/%Y/%m/", blank=True)
    is_blacklisted = models.BooleanField(default=False)
    blacklist_reason = models.TextField(blank=True)
    loyalty_code = models.CharField(max_length=80, blank=True)
    loyalty_points = models.PositiveIntegerField(default=0)
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["property", "full_name"]
        constraints = [models.UniqueConstraint(fields=["property", "license_number"], name="unique_driver_license_per_property")]


class RentalPrivacyEvent(models.Model):
    class EventType(models.TextChoices):
        CONSENT = "consent", _("Consent")
        DOCUMENT_UPLOAD = "document_upload", _("Document upload")
        DATA_EXPORT = "data_export", _("Data export")
        DELETION_REQUEST = "deletion_request", _("Deletion request")

    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="rental_privacy_events")
    booking = models.ForeignKey(VehicleRentalBooking, on_delete=models.SET_NULL, null=True, blank=True, related_name="privacy_events")
    driver_profile = models.ForeignKey(RentalDriverProfile, on_delete=models.SET_NULL, null=True, blank=True, related_name="privacy_events")
    event_type = models.CharField(max_length=32, choices=EventType.choices)
    policy_version = models.CharField(max_length=40, blank=True)
    consent_given = models.BooleanField(default=False)
    requester_email = models.EmailField(blank=True)
    source = models.CharField(max_length=24, default="public")
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class RentalDataRequest(models.Model):
    class RequestType(models.TextChoices):
        EXPORT = "export", _("Export")
        DELETION = "deletion", _("Deletion")

    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        COMPLETED = "completed", _("Completed")
        REJECTED = "rejected", _("Rejected")

    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="rental_data_requests")
    booking = models.ForeignKey(VehicleRentalBooking, on_delete=models.SET_NULL, null=True, blank=True, related_name="data_requests")
    driver_profile = models.ForeignKey(RentalDriverProfile, on_delete=models.SET_NULL, null=True, blank=True, related_name="data_requests")
    request_type = models.CharField(max_length=16, choices=RequestType.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    requester_email = models.EmailField()
    notes = models.TextField(blank=True)
    requested_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)


class RentalCancellationPolicy(models.Model):
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="rental_cancellation_policies")
    code = models.SlugField(max_length=80)
    name = models.CharField(max_length=160)
    free_cancellation_hours = models.PositiveIntegerField(default=0)
    cancellation_fee_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    change_allowed = models.BooleanField(default=True)
    no_show_fee_percent = models.DecimalField(max_digits=5, decimal_places=2, default=100)
    is_active = models.BooleanField(default=True)
    terms = models.TextField(blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["property", "code"], name="unique_rental_cancellation_policy")]


class RentalTaxRule(models.Model):
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="rental_tax_rules")
    code = models.SlugField(max_length=80)
    name = models.CharField(max_length=160)
    vat_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    special_tax_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    applies_to = models.CharField(max_length=40, default="rental")
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["property", "code"], name="unique_rental_tax_rule")]


class RentalLocation(models.Model):
    class Kind(models.TextChoices):
        BRANCH = "branch", _("Branch")
        AIRPORT = "airport", _("Airport")
        CITY = "city", _("City")
        HOTEL = "hotel", _("Hotel")
        CUSTOM = "custom", _("Custom")

    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="rental_locations")
    code = models.SlugField(max_length=80)
    name = models.CharField(max_length=180)
    kind = models.CharField(max_length=16, choices=Kind.choices, default=Kind.BRANCH)
    address = models.TextField(blank=True)
    city = models.CharField(max_length=120, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    pickup_fee = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    dropoff_fee = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["property", "name"]
        constraints = [models.UniqueConstraint(fields=["property", "code"], name="unique_rental_location_code")]


class RentalChannelConnection(models.Model):
    class ChannelType(models.TextChoices):
        FIRST_PARTY = "first_party", _("Booking Balkans first-party portal")
        EXTERNAL = "external", _("External channel manager")

    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="rental_channel_connections")
    code = models.SlugField(max_length=80)
    name = models.CharField(max_length=160)
    provider = models.CharField(max_length=120)
    channel_type = models.CharField(max_length=16, choices=ChannelType.choices, default=ChannelType.EXTERNAL)
    endpoint_url = models.URLField(max_length=500, blank=True)
    credential_ref = models.CharField(max_length=180, blank=True, help_text="Secret manager referansı; ham anahtar saklanmaz.")
    supports_inventory = models.BooleanField(default=True)
    supports_rates = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)
    last_sync_at = models.DateTimeField(null=True, blank=True)
    last_sync_status = models.CharField(max_length=24, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["property", "name"]
        constraints = [models.UniqueConstraint(fields=["property", "code"], name="unique_rental_channel_code")]


class RentalChannelMapping(models.Model):
    connection = models.ForeignKey(RentalChannelConnection, on_delete=models.CASCADE, related_name="mappings")
    vehicle = models.ForeignKey(Vehicle, on_delete=models.CASCADE, related_name="rental_channel_mappings")
    external_vehicle_code = models.CharField(max_length=120)
    external_rate_code = models.CharField(max_length=120, blank=True)
    external_location_code = models.CharField(max_length=120, blank=True)
    is_active = models.BooleanField(default=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["connection", "vehicle"], name="unique_rental_channel_vehicle_mapping")]


class VehicleTelemetryEvent(models.Model):
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="vehicle_telemetry_events")
    vehicle = models.ForeignKey(Vehicle, on_delete=models.CASCADE, related_name="telemetry_events")
    source = models.CharField(max_length=80)
    occurred_at = models.DateTimeField(default=timezone.now)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    mileage = models.PositiveIntegerField(null=True, blank=True)
    speed = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    payload = models.JSONField(default=dict, blank=True)


class RentalFlightStatus(models.Model):
    booking = models.OneToOneField(VehicleRentalBooking, on_delete=models.CASCADE, related_name="flight_status")
    flight_number = models.CharField(max_length=40)
    airport_code = models.CharField(max_length=8, blank=True)
    scheduled_arrival_at = models.DateTimeField(null=True, blank=True)
    estimated_arrival_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=32, default="unknown")
    source = models.CharField(max_length=80, blank=True)
    last_checked_at = models.DateTimeField(null=True, blank=True)
    payload = models.JSONField(default=dict, blank=True)


class ParkingDevice(models.Model):
    class DeviceType(models.TextChoices):
        ANPR = "anpr", "ANPR"
        BARRIER = "barrier", "Bariyer"
        KIOSK = "kiosk", "Kiosk"

    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="parking_devices")
    parking_lot = models.ForeignKey(ParkingLot, on_delete=models.SET_NULL, null=True, blank=True, related_name="devices")
    name = models.CharField(max_length=160)
    device_type = models.CharField(max_length=16, choices=DeviceType.choices)
    endpoint_url = models.URLField(max_length=500, blank=True)
    credential_ref = models.CharField(max_length=180, blank=True)
    is_active = models.BooleanField(default=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    configuration = models.JSONField(default=dict, blank=True)


class RentalExtraProduct(models.Model):
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="rental_extra_products")
    code = models.SlugField(max_length=80)
    name = models.CharField(max_length=160)
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    currency = models.CharField(max_length=3, default="TRY")
    per_day = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["property", "code"], name="unique_rental_extra_code")]


class RentalInsurancePackage(models.Model):
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="rental_insurance_packages")
    code = models.SlugField(max_length=80)
    name = models.CharField(max_length=160)
    coverage = models.TextField(blank=True)
    price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    currency = models.CharField(max_length=3, default="TRY")
    per_day = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["property", "code"], name="unique_rental_insurance_code")]


class RentalHandover(models.Model):
    class Kind(models.TextChoices):
        PICKUP = "pickup", _("Pickup")
        RETURN = "return", _("Return")

    booking = models.ForeignKey(VehicleRentalBooking, on_delete=models.CASCADE, related_name="handovers")
    kind = models.CharField(max_length=12, choices=Kind.choices)
    recorded_at = models.DateTimeField(default=timezone.now)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    mileage = models.PositiveIntegerField(null=True, blank=True)
    fuel_level = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    damage_notes = models.TextField(blank=True)
    signature_file = models.FileField(upload_to="rental-signatures/%Y/%m/", blank=True)
    metadata = models.JSONField(default=dict, blank=True)


class RentalHandoverPhoto(models.Model):
    handover = models.ForeignKey(RentalHandover, on_delete=models.CASCADE, related_name="photos")
    image = models.ImageField(upload_to="rental-handovers/%Y/%m/")
    angle = models.CharField(max_length=80, blank=True)
    note = models.CharField(max_length=240, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class RentalDamageCase(models.Model):
    booking = models.ForeignKey(VehicleRentalBooking, on_delete=models.CASCADE, related_name="damage_cases")
    vehicle = models.ForeignKey(Vehicle, on_delete=models.PROTECT, related_name="damage_cases")
    reference = models.CharField(max_length=40, unique=True, blank=True)
    description = models.TextField()
    estimated_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    insurance_reference = models.CharField(max_length=160, blank=True)
    status = models.CharField(max_length=24, default="open")
    opened_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = f"D-{timezone.now():%y%m%d}-{uuid4().hex[:8].upper()}"
        return super().save(*args, **kwargs)


class VehicleMaintenanceRecord(models.Model):
    vehicle = models.ForeignKey(Vehicle, on_delete=models.CASCADE, related_name="maintenance_records")
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="vehicle_maintenance_records")
    maintenance_type = models.CharField(max_length=100)
    scheduled_at = models.DateField(null=True, blank=True)
    completed_at = models.DateField(null=True, blank=True)
    mileage = models.PositiveIntegerField(null=True, blank=True)
    cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    currency = models.CharField(max_length=3, default="TRY")
    vendor = models.CharField(max_length=180, blank=True)
    status = models.CharField(max_length=24, default="planned")
    notes = models.TextField(blank=True)


class RentalFine(models.Model):
    booking = models.ForeignKey(VehicleRentalBooking, on_delete=models.CASCADE, related_name="fines")
    vehicle = models.ForeignKey(Vehicle, on_delete=models.PROTECT, related_name="rental_fines")
    fine_type = models.CharField(max_length=80)
    reference = models.CharField(max_length=160, blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    currency = models.CharField(max_length=3, default="TRY")
    status = models.CharField(max_length=24, default="open")
    passed_to_customer = models.BooleanField(default=False)
    notes = models.TextField(blank=True)
    incurred_at = models.DateTimeField(default=timezone.now)


class RentalAuditEvent(models.Model):
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="rental_audit_events")
    booking = models.ForeignKey(VehicleRentalBooking, on_delete=models.SET_NULL, null=True, blank=True, related_name="audit_events")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=80)
    source = models.CharField(max_length=32, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class ParkingSubscription(models.Model):
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="parking_subscriptions")
    parking_lot = models.ForeignKey(ParkingLot, on_delete=models.CASCADE, related_name="subscriptions")
    customer_name = models.CharField(max_length=180)
    customer_email = models.EmailField(blank=True)
    vehicle_plate = models.CharField(max_length=32)
    access_card = models.CharField(max_length=80, blank=True)
    valid_from = models.DateTimeField()
    valid_until = models.DateTimeField()
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    currency = models.CharField(max_length=3, default="TRY")
    is_active = models.BooleanField(default=True)


class ParkingAccessEvent(models.Model):
    class Kind(models.TextChoices):
        ENTRY = "entry", _("Entry")
        EXIT = "exit", _("Exit")

    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="parking_access_events")
    parking_lot = models.ForeignKey(ParkingLot, on_delete=models.PROTECT, related_name="access_events")
    parking_space = models.ForeignKey(ParkingSpace, on_delete=models.SET_NULL, null=True, blank=True, related_name="access_events")
    kind = models.CharField(max_length=8, choices=Kind.choices)
    vehicle_plate = models.CharField(max_length=32)
    reservation = models.ForeignKey(ParkingReservation, on_delete=models.SET_NULL, null=True, blank=True, related_name="access_events")
    anpr_reference = models.CharField(max_length=160, blank=True)
    occurred_at = models.DateTimeField(default=timezone.now)
    metadata = models.JSONField(default=dict, blank=True)


class ParkingValetRecord(models.Model):
    parking_lot = models.ForeignKey(ParkingLot, on_delete=models.CASCADE, related_name="valet_records")
    reservation = models.ForeignKey(ParkingReservation, on_delete=models.SET_NULL, null=True, blank=True, related_name="valet_records")
    vehicle_plate = models.CharField(max_length=32)
    key_reference = models.CharField(max_length=80, blank=True)
    received_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="received_valet_records")
    returned_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="returned_valet_records")
    received_at = models.DateTimeField(default=timezone.now)
    returned_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)


class ParkingPenalty(models.Model):
    parking_lot = models.ForeignKey(ParkingLot, on_delete=models.CASCADE, related_name="penalties")
    vehicle_plate = models.CharField(max_length=32)
    reason = models.CharField(max_length=180)
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    currency = models.CharField(max_length=3, default="TRY")
    status = models.CharField(max_length=24, default="open")
    issued_at = models.DateTimeField(default=timezone.now)
    notes = models.TextField(blank=True)


class RentalContract(models.Model):
    booking = models.OneToOneField(VehicleRentalBooking, on_delete=models.CASCADE, related_name="contract")
    contract_number = models.CharField(max_length=60, unique=True)
    terms = models.TextField(blank=True)
    signed_at = models.DateTimeField(null=True, blank=True)
    signed_by_customer = models.CharField(max_length=180, blank=True)
    signature_file = models.FileField(upload_to="rental-contracts/%Y/%m/", blank=True)
    document_file = models.FileField(upload_to="rental-contracts/%Y/%m/", blank=True)
    status = models.CharField(max_length=24, default="draft")
    created_at = models.DateTimeField(auto_now_add=True)


class RentalPayment(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        AUTHORIZED = "authorized", _("Authorized")
        CAPTURED = "captured", _("Captured")
        REFUNDED = "refunded", _("Refunded")
        FAILED = "failed", _("Failed")

    booking = models.ForeignKey(VehicleRentalBooking, on_delete=models.CASCADE, related_name="payments")
    gateway = models.ForeignKey(PaymentGateway, on_delete=models.SET_NULL, null=True, blank=True, related_name="rental_payments")
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    currency = models.CharField(max_length=3, default="TRY")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    provider_reference = models.CharField(max_length=180, blank=True)
    is_preauthorization = models.BooleanField(default=False)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class DepositHold(models.Model):
    class Status(models.TextChoices):
        HELD = "held", _("Held")
        RELEASED = "released", _("Released")
        PARTIALLY_CAPTURED = "partially_captured", _("Partially captured")
        CAPTURED = "captured", _("Captured")
        FORFEITED = "forfeited", _("Forfeited")

    booking = models.OneToOneField(VehicleRentalBooking, on_delete=models.CASCADE, related_name="deposit_hold")
    payment = models.ForeignKey(RentalPayment, on_delete=models.SET_NULL, null=True, blank=True, related_name="deposit_holds")
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    captured_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    currency = models.CharField(max_length=3, default="TRY")
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.HELD)
    provider_reference = models.CharField(max_length=180, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    held_at = models.DateTimeField(auto_now_add=True)
    released_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)


class RentalSettlement(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        READY = "ready", _("Ready")
        INVOICED = "invoiced", _("Invoiced")

    booking = models.OneToOneField(VehicleRentalBooking, on_delete=models.CASCADE, related_name="settlement")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    extra_mileage_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    late_return_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    damage_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    fuel_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    currency = models.CharField(max_length=3, default="TRY")
    details = models.JSONField(default=dict, blank=True)
    calculated_at = models.DateTimeField(auto_now=True)


class RentalInvoice(models.Model):
    booking = models.ForeignKey(VehicleRentalBooking, on_delete=models.CASCADE, related_name="rental_invoices")
    invoice = models.OneToOneField(Invoice, on_delete=models.PROTECT, related_name="rental_invoice")
    invoice_kind = models.CharField(max_length=24, default="rental")
    created_at = models.DateTimeField(auto_now_add=True)


class EInvoiceTransmission(models.Model):
    """Provider-neutral e-invoice/cari export queue and delivery record."""

    class Status(models.TextChoices):
        QUEUED = "queued", _("Queued")
        EXPORTED = "exported", _("Exported")
        ACCEPTED = "accepted", _("Accepted")
        REJECTED = "rejected", _("Rejected")

    invoice = models.OneToOneField(Invoice, on_delete=models.CASCADE, related_name="e_invoice_transmission")
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="e_invoice_transmissions")
    provider = models.CharField(max_length=80, default="manual")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    external_reference = models.CharField(max_length=180, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    response = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)
    queued_at = models.DateTimeField(auto_now_add=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)


class RentalChannelSyncEvent(models.Model):
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="rental_channel_sync_events")
    channel = models.CharField(max_length=80)
    event_type = models.CharField(max_length=40)
    external_reference = models.CharField(max_length=180, blank=True)
    status = models.CharField(max_length=20, default="pending")
    payload = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)
    occurred_at = models.DateTimeField(auto_now_add=True)


class WebhookEvent(models.Model):
    """Property-scoped idempotency record for signed fleet webhooks."""

    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="webhook_events")
    provider = models.CharField(max_length=40)
    event_id = models.CharField(max_length=180)
    event_type = models.CharField(max_length=80, blank=True)
    status = models.CharField(max_length=20, default="received")
    signature_verified = models.BooleanField(default=False)
    payload = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)
    received_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(
            fields=["property", "provider", "event_id"],
            name="unique_property_webhook_event",
        )]


class RentalNotification(models.Model):
    booking = models.ForeignKey(VehicleRentalBooking, on_delete=models.CASCADE, related_name="notifications")
    channel = models.CharField(max_length=16)
    template_code = models.CharField(max_length=80)
    recipient = models.CharField(max_length=180)
    status = models.CharField(max_length=20, default="pending")
    sent_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

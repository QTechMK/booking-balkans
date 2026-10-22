from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from booking.reservations.models import Guest, Reservation
from booking.tenancy.models import Property, Unit


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


class GuestProfileExtension(models.Model):
    guest = models.OneToOneField(Guest, on_delete=models.CASCADE, related_name="profile_extension")
    gender = models.CharField(max_length=24, blank=True)
    birth_date = models.DateField(null=True, blank=True)
    nationality = models.CharField(max_length=80, blank=True)
    identity_reference = models.CharField(max_length=120, blank=True)
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
    domain = models.CharField(max_length=255, blank=True)
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
    two_factor_required = models.BooleanField(default=False)
    last_pin_change = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "property", "role"], name="unique_user_property_role")]

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.role_id and self.property_id and self.role.property_id != self.property_id:
            raise ValidationError({"role": _("Role must belong to the selected property.")})
        if self.valid_from and self.valid_until and self.valid_until < self.valid_from:
            raise ValidationError({"valid_until": _("Validity end cannot be before start.")})


class UserAccessLog(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="access_logs")
    property = models.ForeignKey(Property, on_delete=models.SET_NULL, null=True, blank=True, related_name="access_logs")
    successful = models.BooleanField(default=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=500, blank=True)
    event = models.CharField(max_length=80, default="login")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["property", "created_at"]), models.Index(fields=["user", "created_at"])]

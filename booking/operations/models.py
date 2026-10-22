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
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="currency_definitions")
    code = models.CharField(max_length=3)
    name = models.CharField(max_length=80)
    symbol = models.CharField(max_length=8, blank=True)
    decimal_places = models.PositiveSmallIntegerField(default=2)
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
    source = models.CharField(max_length=80, blank=True)
    is_manual = models.BooleanField(default=False)
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
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="payment_gateways")
    bank_name = models.CharField(max_length=160)
    payment_model = models.CharField(max_length=80, blank=True)
    client_no = models.CharField(max_length=80, blank=True)
    account_name = models.CharField(max_length=160, blank=True)
    pos_name = models.CharField(max_length=120, blank=True)
    currency = models.CharField(max_length=3, default="TRY")
    active = models.BooleanField(default=True)
    default_gate = models.BooleanField(default=False)
    credential_ref = models.CharField(max_length=180, blank=True, help_text="Secret manager reference; never store passwords here.")
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
    payment_method = models.CharField(max_length=16, choices=PaymentMethod.choices, default=PaymentMethod.INVOICE)
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["property", "code"], name="unique_agency_code_per_property")]

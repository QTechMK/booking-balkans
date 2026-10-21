from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from booking.reservations.models import Guest
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
    completed_at = models.DateTimeField(null=True, blank=True)
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
    note = models.TextField(blank=True)
    due_at = models.DateTimeField(null=True, blank=True)
    inspected_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["status", "-updated_at"]
        indexes = [models.Index(fields=["property", "status"]), models.Index(fields=["unit", "status"])]

    def __str__(self):
        return f"{self.unit.code} - {self.get_status_display()}"


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
    resolved_at = models.DateTimeField(null=True, blank=True)
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


class OnlineBookingSettings(models.Model):
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
    seo_title = models.CharField(max_length=180, blank=True)
    seo_description = models.TextField(blank=True)
    meta_keywords = models.CharField(max_length=255, blank=True)
    domain = models.CharField(max_length=255, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

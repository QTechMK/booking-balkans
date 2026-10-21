import builtins
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.utils import timezone

from booking.tenancy.models import Property
from booking.tenancy.models import RatePlan
from booking.tenancy.models import Unit
from booking.tenancy.models import UnitType


class Guest(models.Model):
    """A guest profile scoped to a property."""

    property = models.ForeignKey(
        Property,
        on_delete=models.CASCADE,
        related_name="guests",
    )
    first_name = models.CharField(_("first name"), max_length=120)
    last_name = models.CharField(_("last name"), max_length=120, blank=True)
    email = models.EmailField(_("email"), blank=True)
    phone = models.CharField(_("phone"), max_length=40, blank=True)
    country = models.CharField(_("country"), max_length=2, blank=True)
    notes = models.TextField(_("notes"), blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["last_name", "first_name"]
        indexes = [
            models.Index(fields=["property", "email"]),
            models.Index(fields=["property", "last_name", "first_name"]),
        ]

    def __str__(self) -> str:
        full_name = f"{self.first_name} {self.last_name}".strip()
        return f"{full_name} ({self.email})" if self.email else full_name


class ReservationStatus(models.TextChoices):
    PENDING = "pending", _("Pending")
    CONFIRMED = "confirmed", _("Confirmed")
    CANCELLED = "cancelled", _("Cancelled")
    COMPLETED = "completed", _("Completed")
    NO_SHOW = "no_show", _("No show")


class ReservationSource(models.TextChoices):
    DIRECT = "direct", _("Direct")
    MARKETPLACE = "marketplace", _("Marketplace")
    WIDGET = "widget", _("Widget")
    B2B = "b2b", _("B2B")
    MANUAL = "manual", _("Manual")
    CHANNEL_MANAGER = "channel_manager", _("Channel Manager")


class ReservationChannel(models.Model):
    """A property-scoped booking channel that can be managed by the business."""

    property = models.ForeignKey(
        Property,
        on_delete=models.CASCADE,
        related_name="reservation_channels",
    )
    code = models.SlugField(max_length=80)
    name = models.CharField(max_length=120)
    website_name = models.CharField(max_length=160, blank=True)
    website_url = models.URLField(blank=True)
    website_domain = models.CharField(max_length=255, blank=True)
    widget_key = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    source = models.CharField(
        max_length=24,
        choices=ReservationSource.choices,
        default=ReservationSource.MANUAL,
    )
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["property", "code"],
                name="unique_reservation_channel_per_property",
            ),
        ]
        indexes = [
            models.Index(fields=["property", "is_active", "sort_order"]),
        ]

    def __str__(self) -> str:
        return f"{self.property.name} - {self.name}"


class StayStatus(models.TextChoices):
    NOT_ARRIVED = "not_arrived", _("Not arrived")
    CHECKED_IN = "checked_in", _("Checked in")
    CHECKED_OUT = "checked_out", _("Checked out")
    EARLY_CHECKOUT = "early_checkout", _("Early checkout")


def generate_reference() -> str:
    return uuid.uuid4().hex[:12].upper()


class Reservation(models.Model):
    """A booking header with immutable monetary snapshot fields."""

    property = models.ForeignKey(
        Property,
        on_delete=models.CASCADE,
        related_name="reservations",
    )
    guest = models.ForeignKey(
        Guest,
        on_delete=models.PROTECT,
        related_name="reservations",
    )
    reference = models.CharField(
        _("reference"),
        max_length=20,
        unique=True,
        default=generate_reference,
        editable=False,
    )
    status = models.CharField(
        _("status"),
        max_length=20,
        choices=ReservationStatus.choices,
        default=ReservationStatus.PENDING,
    )
    source = models.CharField(
        _("source"),
        max_length=24,
        choices=ReservationSource.choices,
        default=ReservationSource.DIRECT,
    )
    channel = models.ForeignKey(
        ReservationChannel,
        on_delete=models.SET_NULL,
        related_name="reservations",
        null=True,
        blank=True,
    )
    check_in = models.DateField(_("check-in"))
    check_out = models.DateField(_("check-out"))
    currency = models.CharField(_("currency"), max_length=3, default="TRY")
    subtotal_amount = models.DecimalField(
        _("subtotal"), max_digits=12, decimal_places=2, default=0
    )
    tax_amount = models.DecimalField(
        _("tax"), max_digits=12, decimal_places=2, default=0
    )
    total_amount = models.DecimalField(
        _("total"), max_digits=12, decimal_places=2, default=0
    )
    price_snapshot = models.JSONField(_("price snapshot"), default=dict, blank=True)
    notes = models.TextField(_("notes"), blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_reservations",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["property", "status", "check_in"]),
            models.Index(fields=["property", "check_out"]),
            models.Index(fields=["guest", "created_at"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(check_out__gt=models.F("check_in")),
                name="reservation_check_out_after_check_in",
            ),
            models.CheckConstraint(
                condition=models.Q(subtotal_amount__gte=0)
                & models.Q(tax_amount__gte=0)
                & models.Q(total_amount__gte=0),
                name="reservation_amounts_non_negative",
            ),
        ]

    def clean(self) -> None:
        if self.check_out <= self.check_in:
            raise ValidationError({"check_out": _("Check-out must be after check-in.")})
        if self.guest_id and self.property_id:
            if self.guest.property_id != self.property_id:
                raise ValidationError(
                    {"guest": _("Guest must belong to the same property.")}
                )
        if self.total_amount < 0 or self.subtotal_amount < 0 or self.tax_amount < 0:
            raise ValidationError(_("Reservation amounts cannot be negative."))

    def __str__(self) -> str:
        return self.reference

    @builtins.property
    def stay_status(self) -> str:
        """Aggregate operational stay status across reservation items."""
        statuses = set(self.items.values_list("stay_status", flat=True))
        if not statuses or statuses == {StayStatus.NOT_ARRIVED}:
            return StayStatus.NOT_ARRIVED
        if statuses <= {StayStatus.CHECKED_OUT, StayStatus.EARLY_CHECKOUT}:
            return (
                StayStatus.EARLY_CHECKOUT
                if StayStatus.EARLY_CHECKOUT in statuses
                else StayStatus.CHECKED_OUT
            )
        if StayStatus.CHECKED_IN in statuses:
            return StayStatus.CHECKED_IN
        return StayStatus.NOT_ARRIVED


class ReservationItem(models.Model):
    """A booked unit type/rate product within a reservation."""

    reservation = models.ForeignKey(
        Reservation,
        on_delete=models.CASCADE,
        related_name="items",
    )
    unit_type = models.ForeignKey(
        UnitType,
        on_delete=models.PROTECT,
        related_name="reservation_items",
    )
    rate_plan = models.ForeignKey(
        RatePlan,
        on_delete=models.PROTECT,
        related_name="reservation_items",
    )
    unit = models.ForeignKey(
        Unit,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="reservation_items",
    )
    quantity = models.PositiveIntegerField(_("quantity"), default=1)
    adults = models.PositiveIntegerField(_("adults"), default=1)
    children = models.PositiveIntegerField(_("children"), default=0)
    stay_status = models.CharField(
        _("stay status"),
        max_length=20,
        choices=StayStatus.choices,
        default=StayStatus.NOT_ARRIVED,
    )
    checked_in_at = models.DateTimeField(_("checked in at"), null=True, blank=True)
    checked_in_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="checked_in_reservation_items",
    )
    checked_out_at = models.DateTimeField(_("checked out at"), null=True, blank=True)
    checked_out_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="checked_out_reservation_items",
    )
    nightly_amount = models.DecimalField(
        _("nightly amount"), max_digits=12, decimal_places=2, default=0
    )
    total_amount = models.DecimalField(
        _("total amount"), max_digits=12, decimal_places=2, default=0
    )
    price_snapshot = models.JSONField(_("price snapshot"), default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["reservation", "id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0),
                name="reservation_item_quantity_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(nightly_amount__gte=0)
                & models.Q(total_amount__gte=0),
                name="reservation_item_amounts_non_negative",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(checked_out_at__isnull=True)
                    | models.Q(checked_in_at__isnull=False)
                ),
                name="reservation_item_checkout_requires_checkin",
            ),
        ]
        indexes = [
            models.Index(fields=["reservation", "unit_type"]),
            models.Index(fields=["unit", "reservation"]),
        ]

    def clean(self) -> None:
        reservation_property_id = self.reservation.property_id if self.reservation_id else None
        if self.unit_type_id and reservation_property_id:
            if self.unit_type.property_id != reservation_property_id:
                raise ValidationError(
                    {"unit_type": _("Unit type must belong to the reservation property.")}
                )
        if self.rate_plan_id and self.unit_type_id:
            if self.rate_plan.unit_type_id != self.unit_type_id:
                raise ValidationError(
                    {"rate_plan": _("Rate plan must belong to the selected unit type.")}
                )
        if self.unit_id and reservation_property_id:
            if self.unit.property_id != reservation_property_id:
                raise ValidationError(
                    {"unit": _("Unit must belong to the reservation property.")}
                )
            if self.unit.unit_type_id != self.unit_type_id:
                raise ValidationError(
                    {"unit": _("Unit must belong to the selected unit type.")}
                )
        if self.nightly_amount < 0 or self.total_amount < 0:
            raise ValidationError(_("Reservation item amounts cannot be negative."))
        if self.checked_out_at and not self.checked_in_at:
            raise ValidationError(
                {"checked_out_at": _("Check-out requires a check-in timestamp.")}
            )
        if (
            self.checked_in_at
            and self.checked_out_at
            and self.checked_out_at < self.checked_in_at
        ):
            raise ValidationError(
                {"checked_out_at": _("Check-out cannot be before check-in.")}
            )
        if self.stay_status == StayStatus.NOT_ARRIVED and (
            self.checked_in_at or self.checked_out_at
        ):
            raise ValidationError(
                {"stay_status": _("A timestamp requires an active stay status.")}
            )
        if self.stay_status == StayStatus.CHECKED_IN and not self.checked_in_at:
            raise ValidationError(
                {"checked_in_at": _("Checked-in items require a check-in timestamp.")}
            )
        if self.stay_status in {StayStatus.CHECKED_OUT, StayStatus.EARLY_CHECKOUT} and (
            not self.checked_in_at or not self.checked_out_at
        ):
            raise ValidationError(
                _("Checked-out items require both check-in and check-out timestamps.")
            )

    def check_in(self, *, actor=None, at=None, save=True) -> "ReservationItem":
        if self.stay_status != StayStatus.NOT_ARRIVED:
            raise ValidationError(_("Only not-arrived items can be checked in."))
        self.stay_status = StayStatus.CHECKED_IN
        self.checked_in_at = at or timezone.now()
        self.checked_in_by = actor
        if save:
            self.save(update_fields=["stay_status", "checked_in_at", "checked_in_by", "updated_at"])
        return self

    def check_out(self, *, actor=None, at=None, early=False, save=True) -> "ReservationItem":
        if self.stay_status != StayStatus.CHECKED_IN:
            raise ValidationError(_("Only checked-in items can be checked out."))
        checkout_at = at or timezone.now()
        if self.checked_in_at and checkout_at < self.checked_in_at:
            raise ValidationError(_("Check-out cannot be before check-in."))
        self.stay_status = StayStatus.EARLY_CHECKOUT if early else StayStatus.CHECKED_OUT
        self.checked_out_at = checkout_at
        self.checked_out_by = actor
        if save:
            self.save(update_fields=["stay_status", "checked_out_at", "checked_out_by", "updated_at"])
        return self

    def __str__(self) -> str:
        return f"{self.reservation.reference} - {self.unit_type.name}"


class HoldStatus(models.TextChoices):
    ACTIVE = "active", _("Active")
    CONVERTED = "converted", _("Converted")
    EXPIRED = "expired", _("Expired")
    CANCELLED = "cancelled", _("Cancelled")


class ReservationHold(models.Model):
    """Temporary capacity reservation used during checkout."""

    property = models.ForeignKey(
        Property,
        on_delete=models.CASCADE,
        related_name="reservation_holds",
    )
    unit_type = models.ForeignKey(
        UnitType,
        on_delete=models.PROTECT,
        related_name="reservation_holds",
    )
    rate_plan = models.ForeignKey(
        RatePlan,
        on_delete=models.PROTECT,
        related_name="reservation_holds",
    )
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    check_in = models.DateField(_("check-in"))
    check_out = models.DateField(_("check-out"))
    quantity = models.PositiveIntegerField(_("quantity"), default=1)
    expires_at = models.DateTimeField(_("expires at"))
    status = models.CharField(
        _("status"),
        max_length=20,
        choices=HoldStatus.choices,
        default=HoldStatus.ACTIVE,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_reservation_holds",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["property", "status", "expires_at"]),
            models.Index(fields=["unit_type", "check_in", "check_out"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(check_out__gt=models.F("check_in")),
                name="hold_check_out_after_check_in",
            ),
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0),
                name="hold_quantity_positive",
            ),
        ]

    def clean(self) -> None:
        if self.check_out <= self.check_in:
            raise ValidationError({"check_out": _("Check-out must be after check-in.")})
        if self.unit_type_id and self.property_id:
            if self.unit_type.property_id != self.property_id:
                raise ValidationError(
                    {"unit_type": _("Unit type must belong to the hold property.")}
                )
        if self.rate_plan_id and self.unit_type_id:
            if self.rate_plan.unit_type_id != self.unit_type_id:
                raise ValidationError(
                    {"rate_plan": _("Rate plan must belong to the selected unit type.")}
                )
        if self.quantity < 1:
            raise ValidationError({"quantity": _("Hold quantity must be positive.")})

    def __str__(self) -> str:
        return f"{self.token} - {self.status}"

from django.conf import settings
from django.db import models
import uuid
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _


class BusinessType(models.TextChoices):
    OTL_S = "OTL-S", _("Boutique or small hotel")
    OTL_L = "OTL-L", _("Resort or large hotel")
    APT = "APT", _("Apartment, pension or hostel")
    VIL = "VIL", _("Villa or rental accommodation")
    ACN = "ACN", _("Tour agency")
    BGS = "BGS", _("Independent website business")
    ZNC = "ZNC", _("Chain or multi-property")


class Organization(models.Model):
    """Tenant root shared by one or more properties."""

    name = models.CharField(_("name"), max_length=255)
    slug = models.SlugField(_("slug"), max_length=120, unique=True)
    business_type_default = models.CharField(
        _("default business type"),
        max_length=10,
        choices=BusinessType.choices,
        default=BusinessType.OTL_S,
    )
    country = models.CharField(_("country"), max_length=2, default="TR")
    default_currency = models.CharField(
        _("default currency"),
        max_length=3,
        default="TRY",
    )
    timezone = models.CharField(
        _("time zone"),
        max_length=64,
        default="Europe/Istanbul",
    )
    is_active = models.BooleanField(_("active"), default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Property(models.Model):
    """A bookable or managed property belonging to an organization."""

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="properties",
    )
    name = models.CharField(_("name"), max_length=255)
    slug = models.SlugField(_("slug"), max_length=120)
    business_type = models.CharField(
        _("business type"),
        max_length=10,
        choices=BusinessType.choices,
        default=BusinessType.OTL_S,
    )
    address = models.TextField(_("address"), blank=True)
    city = models.CharField(_("city"), max_length=120, blank=True)
    country = models.CharField(_("country"), max_length=2, default="TR")
    document_number = models.CharField(
        _("license or document number"),
        max_length=120,
        blank=True,
    )
    timezone = models.CharField(
        _("time zone"),
        max_length=64,
        default="Europe/Istanbul",
    )
    currency = models.CharField(_("currency"), max_length=3, default="TRY")
    fleet_widget_key = models.UUIDField(null=True, blank=True, unique=True, editable=False)
    fleet_widget_domain = models.CharField(
        max_length=255,
        blank=True,
        help_text=_("Allowed website domain for the vehicle and parking iframe widget."),
    )
    is_active = models.BooleanField(_("active"), default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "slug"],
                name="unique_property_slug_per_organization",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.organization.name} - {self.name}"

    def save(self, *args, **kwargs):
        if not self.fleet_widget_key:
            self.fleet_widget_key = uuid.uuid4()
        return super().save(*args, **kwargs)


class PropertyModuleLicense(models.Model):
    """Property-scoped product licence for independently sellable modules."""

    class Module(models.TextChoices):
        HOTEL_ERP = "hotel_erp", _("Hotel ERP")
        VEHICLE_RENTAL = "vehicle_rental", _("Vehicle rental")
        PARKING = "parking", _("Parking")

    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="module_licenses")
    module = models.CharField(max_length=32, choices=Module.choices)
    plan_code = models.CharField(max_length=80, blank=True)
    is_enabled = models.BooleanField(default=True)
    starts_at = models.DateField(null=True, blank=True)
    ends_at = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["property", "module"]
        constraints = [models.UniqueConstraint(fields=["property", "module"], name="unique_property_module_license")]

    def __str__(self):
        return f"{self.property.name} - {self.get_module_display()}"

    def is_current(self, on_date=None):
        from django.utils import timezone
        on_date = on_date or timezone.localdate()
        return self.is_enabled and (self.starts_at is None or self.starts_at <= on_date) and (self.ends_at is None or self.ends_at >= on_date)


class PropertySettings(models.Model):
    """Hotel-level operational and contact settings."""

    property = models.OneToOneField(Property, on_delete=models.CASCADE, related_name="settings")
    hotel_group = models.CharField(max_length=160, blank=True)
    sub_hotel = models.CharField(max_length=160, blank=True)
    owner_name = models.CharField(max_length=160, blank=True)
    contact_name = models.CharField(max_length=160, blank=True)
    authorized_person = models.CharField(max_length=160, blank=True)
    subdomain = models.SlugField(max_length=120, blank=True)
    reservation_email = models.EmailField(blank=True)
    accounting_email = models.EmailField(blank=True)
    purchasing_email = models.EmailField(blank=True)
    front_office_email = models.EmailField(blank=True)
    general_manager_email = models.EmailField(blank=True)
    website = models.URLField(blank=True)
    phone = models.CharField(max_length=40, blank=True)
    sms_phone = models.CharField(max_length=40, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    star_rating = models.PositiveSmallIntegerField(null=True, blank=True)
    concept = models.CharField(max_length=120, blank=True)
    description = models.TextField(blank=True)
    check_in_time = models.TimeField(null=True, blank=True)
    check_out_time = models.TimeField(null=True, blank=True)
    system_date = models.DateField(null=True, blank=True)
    pos_currency = models.CharField(max_length=3, blank=True)
    standard_pax_formula = models.CharField(max_length=120, blank=True)
    board_split_method = models.CharField(max_length=120, blank=True)
    door_card_type = models.CharField(max_length=80, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.property.name} settings"


class PropertyDictionaryBase(models.Model):
    property = models.ForeignKey(Property, on_delete=models.CASCADE)
    code = models.SlugField(max_length=80)
    name = models.CharField(max_length=160)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        abstract = True
        ordering = ["property", "name"]


class RoomGroup(PropertyDictionaryBase):
    class Meta(PropertyDictionaryBase.Meta):
        constraints = [models.UniqueConstraint(fields=["property", "code"], name="unique_room_group_code_per_property")]


class BedType(PropertyDictionaryBase):
    class Meta(PropertyDictionaryBase.Meta):
        constraints = [models.UniqueConstraint(fields=["property", "code"], name="unique_bed_type_code_per_property")]


class RoomView(PropertyDictionaryBase):
    class Meta(PropertyDictionaryBase.Meta):
        constraints = [models.UniqueConstraint(fields=["property", "code"], name="unique_room_view_code_per_property")]


class RoomLocation(PropertyDictionaryBase):
    class Meta(PropertyDictionaryBase.Meta):
        constraints = [models.UniqueConstraint(fields=["property", "code"], name="unique_room_location_code_per_property")]


class RoomAmenity(PropertyDictionaryBase):
    class Meta(PropertyDictionaryBase.Meta):
        constraints = [models.UniqueConstraint(fields=["property", "code"], name="unique_room_amenity_code_per_property")]


class BoardType(PropertyDictionaryBase):
    extra_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    child_extra_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    baby_extra_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    currency = models.CharField(max_length=3, default="TRY")
    show_online = models.BooleanField(default=True)

    class Meta(PropertyDictionaryBase.Meta):
        constraints = [models.UniqueConstraint(fields=["property", "code"], name="unique_board_type_code_per_property")]


class RateType(PropertyDictionaryBase):
    is_refundable = models.BooleanField(default=True)
    prepayment_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    price_factor = models.DecimalField(max_digits=8, decimal_places=4, default=1)
    cancellation_until_hours = models.PositiveIntegerField(default=0)
    cancellation_penalty_days = models.PositiveIntegerField(default=0)
    min_nights = models.PositiveIntegerField(default=1)
    max_nights = models.PositiveIntegerField(null=True, blank=True)
    show_online = models.BooleanField(default=True)

    class Meta(PropertyDictionaryBase.Meta):
        constraints = [models.UniqueConstraint(fields=["property", "code"], name="unique_rate_type_code_per_property")]

    def clean(self) -> None:
        from django.core.exceptions import ValidationError
        if self.max_nights is not None and self.max_nights < self.min_nights:
            raise ValidationError({"max_nights": _("Maximum nights cannot be below minimum nights.")})
        if self.prepayment_percent < 0 or self.prepayment_percent > 100:
            raise ValidationError({"prepayment_percent": _("Prepayment percent must be between 0 and 100.")})
        if self.price_factor <= 0:
            raise ValidationError({"price_factor": _("Price factor must be greater than zero.")})


class CancellationOptionRule(models.Model):
    """Property-scoped cancellation/option rule used by a rate type."""

    class PenaltyType(models.TextChoices):
        NONE = "none", _("No penalty")
        PERCENT = "percent", _("Percentage")
        NIGHTS = "nights", _("Night count")
        FULL = "full", _("Full amount")

    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="cancellation_option_rules")
    rate_type = models.ForeignKey(RateType, on_delete=models.SET_NULL, null=True, blank=True, related_name="cancellation_rules")
    name = models.CharField(max_length=160)
    cancellation_until_hours = models.PositiveIntegerField(default=0)
    option_hours = models.PositiveIntegerField(default=0)
    penalty_type = models.CharField(max_length=12, choices=PenaltyType.choices, default=PenaltyType.NONE)
    penalty_value = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    applies_from = models.DateField(null=True, blank=True)
    applies_until = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["property", "name"]
        constraints = [models.UniqueConstraint(fields=["property", "name"], name="unique_cancellation_rule_name")]


class UnitTypeKind(models.TextChoices):
    ROOM = "room", _("Hotel room")
    APARTMENT = "apartment", _("Apartment")
    VILLA = "villa", _("Villa")
    DORM = "dorm", _("Dormitory")


class InventoryMode(models.TextChoices):
    UNIT = "unit", _("Physical units")
    CAPACITY = "capacity", _("Capacity")
    BED = "bed", _("Beds")


class UnitStatus(models.TextChoices):
    ACTIVE = "active", _("Active")
    OUT_OF_SERVICE = "out_of_service", _("Out of service")
    MAINTENANCE = "maintenance", _("Maintenance")


class BedStatus(models.TextChoices):
    ACTIVE = "active", _("Active")
    OUT_OF_SERVICE = "out_of_service", _("Out of service")
    MAINTENANCE = "maintenance", _("Maintenance")


class UnitType(models.Model):
    """Sellable inventory category such as a room or an apartment type."""

    property = models.ForeignKey(
        Property,
        on_delete=models.CASCADE,
        related_name="unit_types",
    )
    room_group = models.ForeignKey(RoomGroup, on_delete=models.SET_NULL, null=True, blank=True, related_name="unit_types")
    name = models.CharField(_("name"), max_length=160)
    code = models.SlugField(_("code"), max_length=80)
    kind = models.CharField(
        _("kind"),
        max_length=20,
        choices=UnitTypeKind.choices,
        default=UnitTypeKind.ROOM,
    )
    inventory_mode = models.CharField(
        _("inventory mode"),
        max_length=20,
        choices=InventoryMode.choices,
        default=InventoryMode.UNIT,
    )
    capacity_per_unit = models.PositiveIntegerField(
        _("capacity per unit"),
        default=1,
    )
    max_adults = models.PositiveIntegerField(_("maximum adults"), default=2)
    max_children = models.PositiveIntegerField(_("maximum children"), default=0)
    bed_count = models.PositiveIntegerField(_("bed count"), default=1)
    max_infants = models.PositiveIntegerField(default=0)
    child_age_from = models.PositiveSmallIntegerField(null=True, blank=True)
    child_age_to = models.PositiveSmallIntegerField(null=True, blank=True)
    infant_age_to = models.PositiveSmallIntegerField(null=True, blank=True)
    description = models.TextField(blank=True)
    amenities = models.ManyToManyField("RoomAmenity", blank=True, related_name="unit_types")
    is_active = models.BooleanField(_("active"), default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["property", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["property", "code"],
                name="unique_unit_type_code_per_property",
            ),
            models.CheckConstraint(
                condition=models.Q(capacity_per_unit__gt=0),
                name="unit_type_capacity_positive",
            ),
        ]

    def clean(self) -> None:
        from django.core.exceptions import ValidationError
        if self.room_group_id and self.property_id and self.room_group.property_id != self.property_id:
            raise ValidationError({"room_group": _("Room group must belong to the same property.")})
        if self.child_age_from is not None and self.child_age_to is not None and self.child_age_to < self.child_age_from:
            raise ValidationError({"child_age_to": _("Child age end cannot be below child age start.")})
        if self.infant_age_to is not None and self.child_age_from is not None and self.infant_age_to > self.child_age_from:
            raise ValidationError({"infant_age_to": _("Infant age end cannot exceed child age start.")})

    def __str__(self) -> str:
        return f"{self.property.name} - {self.name}"


class RoomPhoto(models.Model):
    """A property-scoped photo reference for a room type or physical room."""

    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="room_photos")
    unit_type = models.ForeignKey(UnitType, on_delete=models.CASCADE, null=True, blank=True, related_name="photos")
    unit = models.ForeignKey("Unit", on_delete=models.CASCADE, null=True, blank=True, related_name="photos")
    image = models.ImageField(upload_to="room-photos/%Y/%m/", blank=True)
    image_url = models.URLField(max_length=500, blank=True)
    alt_text = models.CharField(max_length=160, blank=True)
    is_primary = models.BooleanField(default=False)
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sort_order", "id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(unit_type__isnull=False) | models.Q(unit__isnull=False),
                name="room_photo_has_target",
            ),
        ]

    def clean(self) -> None:
        from django.core.exceptions import ValidationError
        if not self.image and not self.image_url:
            raise ValidationError({"image": _("A room photo must have an uploaded image or an image URL.")})
        if self.unit_type_id and self.unit_type.property_id != self.property_id:
            raise ValidationError({"unit_type": _("Room type must belong to the same property.")})
        if self.unit_id and self.unit.property_id != self.property_id:
            raise ValidationError({"unit": _("Room must belong to the same property.")})
        if self.unit_type_id and self.unit_id and self.unit.unit_type_id != self.unit_type_id:
            raise ValidationError({"unit": _("Room must belong to the selected room type.")})


class HotelPhoto(models.Model):
    """Photo belonging to the property's general hotel gallery."""

    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="hotel_photos")
    image = models.ImageField(upload_to="hotel-photos/%Y/%m/", blank=True)
    image_url = models.URLField(max_length=500, blank=True)
    category = models.CharField(max_length=80, blank=True)
    alt_text = models.CharField(max_length=160, blank=True)
    is_primary = models.BooleanField(default=False)
    sort_order = models.PositiveIntegerField(default=0)
    show_online = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sort_order", "id"]

    def clean(self) -> None:
        from django.core.exceptions import ValidationError
        if not self.image and not self.image_url:
            raise ValidationError({"image": _("A hotel photo must have an uploaded image or an image URL.")})


class Unit(models.Model):
    """A physical room, villa, apartment or dorm room."""

    property = models.ForeignKey(
        Property,
        on_delete=models.CASCADE,
        related_name="units",
    )
    unit_type = models.ForeignKey(
        UnitType,
        on_delete=models.PROTECT,
        related_name="units",
    )
    bed_type = models.ForeignKey(BedType, on_delete=models.SET_NULL, null=True, blank=True, related_name="units")
    room_view = models.ForeignKey(RoomView, on_delete=models.SET_NULL, null=True, blank=True, related_name="units")
    room_location = models.ForeignKey(RoomLocation, on_delete=models.SET_NULL, null=True, blank=True, related_name="units")
    code = models.CharField(_("code"), max_length=80)
    name = models.CharField(_("name"), max_length=160, blank=True)
    status = models.CharField(
        _("status"),
        max_length=20,
        choices=UnitStatus.choices,
        default=UnitStatus.ACTIVE,
    )
    floor = models.CharField(_("floor"), max_length=40, blank=True)
    description = models.TextField(blank=True)
    phone = models.CharField(max_length=40, blank=True)
    owner_name = models.CharField(max_length=160, blank=True)
    is_locked = models.BooleanField(default=False)
    out_of_service_from = models.DateField(null=True, blank=True)
    out_of_service_to = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(_("active"), default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["property", "code"]
        constraints = [
            models.UniqueConstraint(
                fields=["property", "code"],
                name="unique_unit_code_per_property",
            ),
        ]
        indexes = [
            models.Index(fields=["property", "status"]),
            models.Index(fields=["unit_type", "status"]),
        ]

    def clean(self) -> None:
        from django.core.exceptions import ValidationError

        if self.unit_type_id and self.property_id:
            if self.unit_type.property_id != self.property_id:
                raise ValidationError(
                    {"unit_type": _("Unit type must belong to the same property.")}
                )

    def __str__(self) -> str:
        return f"{self.property.name} - {self.code}"


class Vehicle(models.Model):
    """Property-owned vehicle or transfer asset used by hotel operations."""

    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="vehicles")
    code = models.SlugField(max_length=80)
    name = models.CharField(max_length=160)
    vehicle_type = models.CharField(max_length=80, blank=True)
    vehicle_class = models.CharField(max_length=80, blank=True)
    brand = models.CharField(max_length=80, blank=True)
    model_name = models.CharField(max_length=120, blank=True)
    model_year = models.PositiveSmallIntegerField(null=True, blank=True)
    plate_number = models.CharField(max_length=32, blank=True)
    vin = models.CharField(max_length=64, blank=True)
    fuel_type = models.CharField(max_length=40, blank=True)
    transmission = models.CharField(max_length=32, blank=True)
    door_count = models.PositiveSmallIntegerField(default=4)
    passenger_capacity = models.PositiveSmallIntegerField(default=0)
    luggage_capacity = models.PositiveSmallIntegerField(default=0)
    has_air_conditioning = models.BooleanField(default=True)
    has_navigation = models.BooleanField(default=False)
    has_bluetooth = models.BooleanField(default=False)
    has_usb = models.BooleanField(default=False)
    has_reverse_camera = models.BooleanField(default=False)
    mileage_policy = models.CharField(max_length=32, default="limited")
    fuel_policy = models.CharField(max_length=32, default="full_to_full")
    minimum_driver_age = models.PositiveSmallIntegerField(default=21)
    minimum_license_months = models.PositiveSmallIntegerField(default=12)
    inspection_due_date = models.DateField(null=True, blank=True)
    insurance_due_date = models.DateField(null=True, blank=True)
    insurance_policy_number = models.CharField(max_length=120, blank=True)
    deposit_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    daily_rate = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    rate_currency = models.CharField(max_length=3, default="TRY")
    status = models.CharField(max_length=24, default="available")
    branch = models.CharField(max_length=160, blank=True)
    parking_location = models.CharField(max_length=160, blank=True)
    online_enabled = models.BooleanField(default=False)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["property", "name"]
        constraints = [models.UniqueConstraint(fields=["property", "code"], name="unique_vehicle_code_per_property")]


class VehiclePhoto(models.Model):
    vehicle = models.ForeignKey(Vehicle, on_delete=models.CASCADE, related_name="photos")
    image = models.ImageField(upload_to="vehicle-photos/%Y/%m/")
    alt_text = models.CharField(max_length=180, blank=True)
    is_primary = models.BooleanField(default=False)
    sort_order = models.PositiveSmallIntegerField(default=0)
    show_online = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sort_order", "id"]


class Bed(models.Model):
    """A sellable bed belonging to a physical dormitory unit."""

    unit = models.ForeignKey(
        Unit,
        on_delete=models.CASCADE,
        related_name="beds",
    )
    code = models.CharField(_("code"), max_length=80)
    status = models.CharField(
        _("status"),
        max_length=20,
        choices=BedStatus.choices,
        default=BedStatus.ACTIVE,
    )
    is_active = models.BooleanField(_("active"), default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["unit", "code"]
        constraints = [
            models.UniqueConstraint(
                fields=["unit", "code"],
                name="unique_bed_code_per_unit",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.unit.code} - {self.code}"


class Inventory(models.Model):
    """Daily sellable capacity for a property and unit type."""

    property = models.ForeignKey(
        Property,
        on_delete=models.CASCADE,
        related_name="inventory_days",
    )
    unit_type = models.ForeignKey(
        UnitType,
        on_delete=models.CASCADE,
        related_name="inventory_days",
    )
    date = models.DateField(_("date"))
    total_capacity = models.PositiveIntegerField(_("total capacity"), default=0)
    blocked_capacity = models.PositiveIntegerField(_("blocked capacity"), default=0)
    is_closed = models.BooleanField(_("closed for sale"), default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["date", "property", "unit_type"]
        constraints = [
            models.UniqueConstraint(
                fields=["property", "unit_type", "date"],
                name="unique_inventory_day_per_unit_type",
            ),
            models.CheckConstraint(
                condition=models.Q(blocked_capacity__lte=models.F("total_capacity")),
                name="inventory_blocked_not_above_total",
            ),
        ]
        indexes = [
            models.Index(fields=["property", "date"]),
            models.Index(fields=["unit_type", "date"]),
        ]

    def clean(self) -> None:
        from django.core.exceptions import ValidationError

        if self.unit_type_id and self.property_id:
            if self.unit_type.property_id != self.property_id:
                raise ValidationError(
                    {"unit_type": _("Unit type must belong to the same property.")}
                )
        if self.blocked_capacity > self.total_capacity:
            raise ValidationError(
                {"blocked_capacity": _("Blocked capacity cannot exceed total capacity.")}
            )

    @cached_property
    def sellable_capacity(self) -> int:
        if self.is_closed:
            return 0
        return self.total_capacity - self.blocked_capacity

    def __str__(self) -> str:
        return f"{self.property.name} - {self.unit_type.name} - {self.date}"


class MealPlan(models.TextChoices):
    ROOM_ONLY = "room_only", _("Room only")
    BREAKFAST = "breakfast", _("Breakfast")
    HALF_BOARD = "half_board", _("Half board")
    FULL_BOARD = "full_board", _("Full board")
    ALL_INCLUSIVE = "all_inclusive", _("All inclusive")


class RatePlan(models.Model):
    """A sellable price product for one unit type."""

    property = models.ForeignKey(
        Property,
        on_delete=models.CASCADE,
        related_name="rate_plans",
    )
    unit_type = models.ForeignKey(
        UnitType,
        on_delete=models.PROTECT,
        related_name="rate_plans",
    )
    board_type = models.ForeignKey(BoardType, on_delete=models.SET_NULL, null=True, blank=True, related_name="rate_plans")
    rate_type = models.ForeignKey(RateType, on_delete=models.SET_NULL, null=True, blank=True, related_name="rate_plans")
    name = models.CharField(_("name"), max_length=160)
    code = models.SlugField(_("code"), max_length=80)
    meal_plan = models.CharField(
        _("meal plan"),
        max_length=20,
        choices=MealPlan.choices,
        default=MealPlan.ROOM_ONLY,
    )
    cancellation_policy = models.CharField(
        _("cancellation policy"),
        max_length=120,
        blank=True,
    )
    is_refundable = models.BooleanField(_("refundable"), default=True)
    deposit_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    max_adults = models.PositiveIntegerField(_("maximum adults"), default=2)
    max_children = models.PositiveIntegerField(_("maximum children"), default=0)
    currency = models.CharField(_("currency"), max_length=3, default="TRY")
    min_nights = models.PositiveIntegerField(default=1)
    max_nights = models.PositiveIntegerField(null=True, blank=True)
    season_label = models.CharField(max_length=120, blank=True)
    is_active = models.BooleanField(_("active"), default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["property", "unit_type", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["property", "code"],
                name="unique_rate_plan_code_per_property",
            ),
        ]
        indexes = [
            models.Index(fields=["property", "is_active"]),
            models.Index(fields=["unit_type", "is_active"]),
        ]

    def clean(self) -> None:
        from django.core.exceptions import ValidationError

        if self.unit_type_id and self.property_id:
            if self.unit_type.property_id != self.property_id:
                raise ValidationError(
                    {"unit_type": _("Rate plan must belong to the same property.")}
                )
        for field in ("board_type", "rate_type"):
            value = getattr(self, f"{field}_id")
            if value and getattr(getattr(self, field), "property_id") != self.property_id:
                raise ValidationError({field: _("This definition must belong to the same property.")})
        if self.deposit_percent < 0 or self.deposit_percent > 100:
            raise ValidationError({"deposit_percent": _("Deposit percent must be between 0 and 100.")})
        if self.max_nights is not None and self.max_nights < self.min_nights:
            raise ValidationError({"max_nights": _("Maximum nights cannot be below minimum nights.")})

    def __str__(self) -> str:
        return f"{self.property.name} - {self.name}"


class RatePlanSeason(models.Model):
    """Date-bounded rate-plan season and its optional pricing constraints."""

    rate_plan = models.ForeignKey(RatePlan, on_delete=models.CASCADE, related_name="seasons")
    name = models.CharField(max_length=120)
    valid_from = models.DateField()
    valid_until = models.DateField()
    min_nights = models.PositiveIntegerField(default=1)
    max_nights = models.PositiveIntegerField(null=True, blank=True)
    price_factor = models.DecimalField(max_digits=8, decimal_places=4, default=1)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["rate_plan", "valid_from"]
        constraints = [models.UniqueConstraint(fields=["rate_plan", "name"], name="unique_rate_plan_season_name")]


class RatePlanChannel(models.Model):
    """Explicit channel availability for a rate plan."""

    rate_plan = models.ForeignKey(RatePlan, on_delete=models.CASCADE, related_name="channel_links")
    channel = models.ForeignKey("reservations.ReservationChannel", on_delete=models.CASCADE, related_name="rate_plan_links")
    external_code = models.CharField(max_length=120, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["rate_plan", "channel"], name="unique_rate_plan_channel_link")]


class ChannelRateRuleType(models.TextChoices):
    PERCENT = "percent", _("Percentage")
    FIXED = "fixed", _("Fixed amount")


class ChannelRateRuleDayScope(models.TextChoices):
    ALL = "all", _("All days")
    WEEKDAY = "weekday", _("Weekdays")
    WEEKEND = "weekend", _("Weekends")


class ChannelRateRule(models.Model):
    """A property-scoped adjustment applied to a rate for one sales channel.

    This is an internal commercial rule. It does not represent or control
    Google's Price Accuracy or Competitiveness systems.
    """

    property = models.ForeignKey(
        Property,
        on_delete=models.CASCADE,
        related_name="channel_rate_rules",
    )
    channel = models.ForeignKey(
        "reservations.ReservationChannel",
        on_delete=models.CASCADE,
        related_name="rate_rules",
    )
    rate_plan = models.ForeignKey(
        RatePlan,
        on_delete=models.CASCADE,
        related_name="channel_rate_rules",
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=160)
    rule_type = models.CharField(
        max_length=12,
        choices=ChannelRateRuleType.choices,
        default=ChannelRateRuleType.PERCENT,
    )
    adjustment = models.DecimalField(max_digits=8, decimal_places=2)
    day_scope = models.CharField(max_length=12, choices=ChannelRateRuleDayScope.choices, default=ChannelRateRuleDayScope.ALL)
    external_rate_code = models.CharField(max_length=120, blank=True)
    priority = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["priority", "name"]
        indexes = [
            models.Index(fields=["property", "channel", "is_active"]),
            models.Index(fields=["rate_plan", "is_active"]),
        ]

    def clean(self) -> None:
        from django.core.exceptions import ValidationError

        if self.channel_id and self.property_id:
            if self.channel.property_id != self.property_id:
                raise ValidationError({"channel": _("Channel must belong to the same property.")})
        if self.rate_plan_id and self.property_id:
            if self.rate_plan.property_id != self.property_id:
                raise ValidationError({"rate_plan": _("Rate plan must belong to the same property.")})
        if self.rule_type == ChannelRateRuleType.PERCENT and self.adjustment < -100:
            raise ValidationError({"adjustment": _("Percentage adjustment cannot be below -100.")})

    def __str__(self) -> str:
        return f"{self.property.name} - {self.channel.name} - {self.name}"


class PriceParityStatus(models.TextChoices):
    BELOW = "below", _("Direct price is lower")
    EQUAL = "equal", _("Prices are equal")
    ABOVE = "above", _("Direct price is higher")
    UNCOMPARABLE = "uncomparable", _("Not comparable")


class PriceParityObservation(models.Model):
    """An auditable comparison between direct and an external channel price."""

    property = models.ForeignKey(
        Property,
        on_delete=models.CASCADE,
        related_name="price_parity_observations",
    )
    rate_plan = models.ForeignKey(
        RatePlan,
        on_delete=models.SET_NULL,
        related_name="price_parity_observations",
        null=True,
        blank=True,
    )
    channel = models.ForeignKey(
        "reservations.ReservationChannel",
        on_delete=models.SET_NULL,
        related_name="price_parity_observations",
        null=True,
        blank=True,
    )
    competitor_name = models.CharField(max_length=160)
    check_in = models.DateField()
    check_out = models.DateField()
    adults = models.PositiveIntegerField(default=1)
    children = models.PositiveIntegerField(default=0)
    currency = models.CharField(max_length=3, default="TRY")
    direct_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    competitor_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    terms_match = models.BooleanField(default=False)
    status = models.CharField(
        max_length=16,
        choices=PriceParityStatus.choices,
        default=PriceParityStatus.UNCOMPARABLE,
    )
    terms_snapshot = models.JSONField(default=dict, blank=True)
    observed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-observed_at"]
        indexes = [
            models.Index(fields=["property", "observed_at"]),
            models.Index(fields=["property", "status", "observed_at"]),
        ]

    def clean(self) -> None:
        from django.core.exceptions import ValidationError

        if self.check_out <= self.check_in:
            raise ValidationError({"check_out": _("Check-out must be after check-in.")})
        if self.rate_plan_id and self.rate_plan.property_id != self.property_id:
            raise ValidationError({"rate_plan": _("Rate plan must belong to the same property.")})
        if self.channel_id and self.channel.property_id != self.property_id:
            raise ValidationError({"channel": _("Channel must belong to the same property.")})
        for field in ("direct_amount", "competitor_amount"):
            value = getattr(self, field)
            if value is not None and value < 0:
                raise ValidationError({field: _("Amount cannot be negative.")})

    def classify(self) -> str:
        if not self.terms_match or self.direct_amount is None or self.competitor_amount is None:
            return PriceParityStatus.UNCOMPARABLE
        if self.direct_amount < self.competitor_amount:
            return PriceParityStatus.BELOW
        if self.direct_amount > self.competitor_amount:
            return PriceParityStatus.ABOVE
        return PriceParityStatus.EQUAL

    def save(self, *args, **kwargs):
        self.status = self.classify()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.property.name} - {self.competitor_name} - {self.status}"


class Season(models.Model):
    """A named date range used to organize pricing rules."""

    property = models.ForeignKey(
        Property,
        on_delete=models.CASCADE,
        related_name="seasons",
    )
    name = models.CharField(_("name"), max_length=120)
    code = models.SlugField(_("code"), max_length=80)
    start_date = models.DateField(_("start date"))
    end_date = models.DateField(_("end date"))
    priority = models.PositiveIntegerField(_("priority"), default=0)
    is_active = models.BooleanField(_("active"), default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["property", "start_date", "-priority"]
        constraints = [
            models.UniqueConstraint(
                fields=["property", "code"],
                name="unique_season_code_per_property",
            ),
            models.CheckConstraint(
                condition=models.Q(end_date__gte=models.F("start_date")),
                name="season_end_not_before_start",
            ),
        ]

    def clean(self) -> None:
        from django.core.exceptions import ValidationError

        if self.end_date < self.start_date:
            raise ValidationError({"end_date": _("Season end must not be before start.")})

    def __str__(self) -> str:
        return f"{self.property.name} - {self.name}"


class DailyRate(models.Model):
    """The dated base amount for a rate plan."""

    rate_plan = models.ForeignKey(
        RatePlan,
        on_delete=models.CASCADE,
        related_name="daily_rates",
    )
    date = models.DateField(_("date"))
    amount = models.DecimalField(
        _("amount"),
        max_digits=12,
        decimal_places=2,
    )
    min_nights = models.PositiveIntegerField(_("minimum nights"), default=1)
    max_nights = models.PositiveIntegerField(
        _("maximum nights"),
        null=True,
        blank=True,
    )
    is_closed = models.BooleanField(_("closed for sale"), default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["date", "rate_plan"]
        constraints = [
            models.UniqueConstraint(
                fields=["rate_plan", "date"],
                name="unique_daily_rate_per_plan_date",
            ),
            models.CheckConstraint(
                condition=models.Q(amount__gte=0),
                name="daily_rate_amount_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(max_nights__isnull=True)
                | models.Q(max_nights__gte=models.F("min_nights")),
                name="daily_rate_max_nights_valid",
            ),
        ]
        indexes = [
            models.Index(fields=["rate_plan", "date"]),
        ]

    def clean(self) -> None:
        from django.core.exceptions import ValidationError

        if self.amount < 0:
            raise ValidationError({"amount": _("Rate amount cannot be negative.")})
        if self.max_nights is not None and self.max_nights < self.min_nights:
            raise ValidationError(
                {"max_nights": _("Maximum nights cannot be below minimum nights.")}
            )

    def __str__(self) -> str:
        return f"{self.rate_plan.name} - {self.date}"


class RateRestriction(models.Model):
    """Date-specific sales restrictions for a rate plan."""

    rate_plan = models.ForeignKey(
        RatePlan,
        on_delete=models.CASCADE,
        related_name="restrictions",
    )
    date = models.DateField(_("date"))
    stop_sell = models.BooleanField(_("stop sell"), default=False)
    close_to_arrival = models.BooleanField(_("close to arrival"), default=False)
    close_to_departure = models.BooleanField(_("close to departure"), default=False)
    min_nights = models.PositiveIntegerField(_("minimum nights"), default=1)
    max_nights = models.PositiveIntegerField(
        _("maximum nights"),
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["date", "rate_plan"]
        constraints = [
            models.UniqueConstraint(
                fields=["rate_plan", "date"],
                name="unique_rate_restriction_per_plan_date",
            ),
            models.CheckConstraint(
                condition=models.Q(max_nights__isnull=True)
                | models.Q(max_nights__gte=models.F("min_nights")),
                name="rate_restriction_max_nights_valid",
            ),
        ]

    def clean(self) -> None:
        from django.core.exceptions import ValidationError

        if self.max_nights is not None and self.max_nights < self.min_nights:
            raise ValidationError(
                {"max_nights": _("Maximum nights cannot be below minimum nights.")}
            )

    def __str__(self) -> str:
        return f"{self.rate_plan.name} - restrictions - {self.date}"


class MembershipRole(models.TextChoices):
    OWNER = "owner", _("Owner")
    ADMIN = "admin", _("Administrator")
    MANAGER = "manager", _("Manager")
    RECEPTION = "reception", _("Reception")
    HOUSEKEEPING = "housekeeping", _("Housekeeping")
    REVENUE = "revenue", _("Revenue")
    ACCOUNTING = "accounting", _("Accounting")
    SALES = "sales", _("Sales")
    AGENCY = "agency", _("Agency")
    PROPERTY_OWNER = "property_owner", _("Property owner")


class Membership(models.Model):
    """Connects a user to an organization, optionally at property scope."""

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="organization_memberships",
    )
    property = models.ForeignKey(
        Property,
        on_delete=models.CASCADE,
        related_name="memberships",
        null=True,
        blank=True,
    )
    role = models.CharField(
        _("role"),
        max_length=32,
        choices=MembershipRole.choices,
    )
    is_active = models.BooleanField(_("active"), default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["organization", "user", "role"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "user", "property", "role"],
                name="unique_membership_scope_role",
            ),
        ]
        indexes = [
            models.Index(fields=["user", "organization"]),
            models.Index(fields=["organization", "property"]),
        ]

    def __str__(self) -> str:
        scope = self.property.name if self.property else "organization"
        return f"{self.user} - {self.organization} - {scope} ({self.role})"

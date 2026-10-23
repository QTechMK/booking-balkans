from django import forms
from django.core.validators import RegexValidator
from django.contrib.auth import get_user_model

from booking.reservations.models import Guest, Reservation
from booking.tenancy.models import (
    BedType, BoardType, HotelPhoto, Property, PropertySettings, RateType, RoomGroup, RoomLocation, RoomPhoto, RoomView, Unit, UnitType, Vehicle, VehiclePhoto,
)
from .models import AccessPermission, Agency, CashierShift, CurrencyDefinition, DailyCurrencyRate, DepartmentDefinition, FrontCashTransaction, FrontOfficeCallRequest, GuestProfileExtension, GuestSegment, Invoice, LoyaltyTier, MarketingCampaign, MessageTemplate, OperationalTask, ParkingAccessEvent, ParkingDevice, ParkingLot, ParkingPenalty, ParkingReservation, ParkingSpace, ParkingSubscription, ParkingValetRecord, PaymentGateway, PropertyRole, PropertyService, RentalAuditEvent, RentalCancellationPolicy, RentalChannelConnection, RentalChannelMapping, RentalContract, RentalDamageCase, RentalDriverProfile, RentalExtraProduct, RentalFine, RentalFlightStatus, RentalHandover, RentalHandoverPhoto, RentalInsurancePackage, RentalInvoice, RentalLocation, RentalNotification, RentalPayment, RentalPricingRule, RentalTaxRule, RentalChannelSyncEvent, RevenueCode, SupportEducationRequest, SupportFAQCategory, SupportFAQItem, SupportReferral, SupportTicket, SupportTicketMessage, TaskGroup, TaskLocation, UserPropertyAccess, VehicleMaintenanceRecord, VehicleRentalBooking, VehicleRentalRate, VehicleTelemetryEvent


class HotelModelForm(forms.ModelForm):
    """Apply the shared Bootstrap/Tixia control classes to generated forms."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            classes = widget.attrs.get("class", "").split()
            if isinstance(widget, forms.CheckboxInput):
                css_class = "form-check-input"
            elif isinstance(widget, (forms.Select, forms.SelectMultiple)):
                css_class = "form-select"
            else:
                css_class = "form-control"
            if css_class not in classes:
                classes.append(css_class)
            widget.attrs["class"] = " ".join(classes)


class PropertySettingsForm(HotelModelForm):
    class Meta:
        model = PropertySettings
        exclude = ["property"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}

    def clean(self):
        cleaned = super().clean()
        latitude = cleaned.get("latitude")
        longitude = cleaned.get("longitude")
        if latitude is not None and not -90 <= latitude <= 90:
            self.add_error("latitude", "Enlem -90 ile 90 arasında olmalıdır.")
        if longitude is not None and not -180 <= longitude <= 180:
            self.add_error("longitude", "Boylam -180 ile 180 arasında olmalıdır.")
        if cleaned.get("check_in_time") and cleaned.get("check_out_time") and cleaned["check_in_time"] == cleaned["check_out_time"]:
            self.add_error("check_out_time", "Check-out saati check-in saatinden farklı olmalıdır.")
        return cleaned


class PropertyProfileForm(HotelModelForm):
    class Meta:
        model = Property
        fields = ["name", "slug", "business_type", "address", "city", "country", "document_number", "timezone", "currency", "is_active"]
        widgets = {"address": forms.Textarea(attrs={"rows": 2})}


class DictionaryForm(HotelModelForm):
    class Meta:
        fields = ["code", "name", "description", "is_active"]


class RoomGroupForm(DictionaryForm):
    class Meta(DictionaryForm.Meta):
        model = RoomGroup


class BedTypeForm(DictionaryForm):
    class Meta(DictionaryForm.Meta):
        model = BedType


class RoomViewForm(DictionaryForm):
    class Meta(DictionaryForm.Meta):
        model = RoomView


class RoomLocationForm(DictionaryForm):
    class Meta(DictionaryForm.Meta):
        model = RoomLocation


class BoardTypeForm(DictionaryForm):
    class Meta(DictionaryForm.Meta):
        model = BoardType
        fields = DictionaryForm.Meta.fields + ["extra_price", "child_extra_price", "baby_extra_price", "currency", "show_online"]
        labels = {
            "code": "Kod", "name": "Ad", "description": "Açıklama", "is_active": "Aktif",
            "extra_price": "Yetişkin ek fiyatı", "child_extra_price": "Çocuk ek fiyatı",
            "baby_extra_price": "Bebek ek fiyatı", "currency": "Para birimi", "show_online": "Online göster",
        }


class RateTypeForm(DictionaryForm):
    class Meta(DictionaryForm.Meta):
        model = RateType
        fields = DictionaryForm.Meta.fields + [
            "is_refundable", "prepayment_percent", "price_factor", "cancellation_until_hours",
            "cancellation_penalty_days", "min_nights", "max_nights", "show_online",
        ]
        labels = {
            "code": "Kod", "name": "Ad", "description": "Açıklama", "is_active": "Aktif",
            "is_refundable": "İade edilebilir", "prepayment_percent": "Peşin ödeme yüzdesi",
            "price_factor": "Fiyat katsayısı", "cancellation_until_hours": "İptal son saati",
            "cancellation_penalty_days": "İptal ceza gecesi", "min_nights": "Minimum gece",
            "max_nights": "Maksimum gece", "show_online": "Online göster",
        }


class RoomPhotoForm(HotelModelForm):
    class Meta:
        model = RoomPhoto
        fields = ["unit_type", "unit", "image", "image_url", "alt_text", "is_primary", "sort_order"]
        widgets = {"image": forms.ClearableFileInput(attrs={"accept": "image/*"})}

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("unit_type") and not cleaned.get("unit"):
            raise forms.ValidationError("Fotoğraf bir oda tipine veya fiziksel odaya bağlanmalıdır.")
        if not cleaned.get("image") and not cleaned.get("image_url"):
            raise forms.ValidationError("Dosya yükleyin veya bir görsel URL'si girin.")
        return cleaned


class HotelPhotoForm(HotelModelForm):
    class Meta:
        model = HotelPhoto
        fields = ["image", "image_url", "category", "alt_text", "is_primary", "sort_order", "show_online"]
        widgets = {"image": forms.ClearableFileInput(attrs={"accept": "image/*"})}

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("image") and not cleaned.get("image_url"):
            raise forms.ValidationError("Dosya yükleyin veya bir görsel URL'si girin.")
        return cleaned


class TaskDictionaryForm(HotelModelForm):
    class Meta:
        fields = ["code", "name", "is_active"]


class TaskGroupForm(TaskDictionaryForm):
    class Meta(TaskDictionaryForm.Meta):
        model = TaskGroup


class TaskLocationForm(TaskDictionaryForm):
    class Meta(TaskDictionaryForm.Meta):
        model = TaskLocation


class OperationalTaskForm(HotelModelForm):
    class Meta:
        model = OperationalTask
        fields = ["group", "location", "unit", "title", "description", "status", "priority", "assigned_to", "due_at", "sla_due_at", "completion_note"]
        widgets = {
            "due_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "sla_due_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "description": forms.Textarea(attrs={"rows": 2}),
            "completion_note": forms.Textarea(attrs={"rows": 2}),
        }


class GuestProfileForm(HotelModelForm):
    class Meta:
        model = GuestProfileExtension
        fields = ["gender", "birth_date", "nationality", "identity_reference", "company_name", "tax_number", "vip", "gdpr_confirmed", "email_confirmed", "phone_confirmed", "preferences", "allergens", "loyalty_code"]
        widgets = {"birth_date": forms.DateInput(attrs={"type": "date"}), "preferences": forms.Textarea(attrs={"rows": 2}), "allergens": forms.Textarea(attrs={"rows": 2})}


class LoyaltyTierForm(HotelModelForm):
    class Meta:
        model = LoyaltyTier
        fields = ["code", "name", "minimum_points", "discount_percent", "is_active"]


class UnitTypeForm(HotelModelForm):
    class Meta:
        model = UnitType
        exclude = ["property", "created_at", "updated_at"]
        widgets = {"description": forms.Textarea(attrs={"rows": 2})}


class UnitForm(HotelModelForm):
    class Meta:
        model = Unit
        exclude = ["property", "created_at", "updated_at"]
        widgets = {"description": forms.Textarea(attrs={"rows": 2})}


class GuestSegmentForm(HotelModelForm):
    vip_only = forms.BooleanField(required=False, label="Yalnızca VIP misafirler")
    gdpr_required = forms.BooleanField(required=False, label="GDPR onayı olanlar")
    country = forms.CharField(required=False, max_length=2, label="Ülke kodu")
    has_email = forms.BooleanField(required=False, initial=True, label="E-posta adresi olanlar")

    class Meta:
        model = GuestSegment
        exclude = ["property", "criteria", "created_at", "updated_at"]
        widgets = {"description": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        criteria = self.instance.criteria or {}
        for field in ("vip_only", "gdpr_required", "has_email"):
            self.fields[field].initial = criteria.get(field, self.fields[field].initial)
        self.fields["country"].initial = criteria.get("country", "")

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.criteria = {
            "vip_only": bool(self.cleaned_data.get("vip_only")),
            "gdpr_required": bool(self.cleaned_data.get("gdpr_required")),
            "has_email": bool(self.cleaned_data.get("has_email")),
        }
        if self.cleaned_data.get("country"):
            obj.criteria["country"] = self.cleaned_data["country"].upper()
        if commit:
            obj.save()
        return obj


class MessageTemplateForm(HotelModelForm):
    class Meta:
        model = MessageTemplate
        exclude = ["property", "updated_at"]
        widgets = {"body": forms.Textarea(attrs={"rows": 5})}


class MarketingCampaignForm(HotelModelForm):
    class Meta:
        model = MarketingCampaign
        exclude = ["property", "sent_at", "created_by", "created_at"]
        widgets = {"scheduled_at": forms.DateTimeInput(attrs={"type": "datetime-local"})}


class PropertyServiceForm(HotelModelForm):
    class Meta:
        model = PropertyService
        exclude = ["property", "created_at", "updated_at"]
        widgets = {"description": forms.Textarea(attrs={"rows": 2})}


DEPARTMENT_CHOICES = (
    ("Front Office", "Front Office"),
    ("Reservations", "Reservations"),
    ("Housekeeping", "Housekeeping"),
    ("Maintenance", "Maintenance"),
    ("Finance", "Finance"),
    ("Management", "Management"),
)


class PropertyRoleForm(HotelModelForm):
    department = forms.ChoiceField(choices=(("", "Departman seçin"),) + DEPARTMENT_CHOICES, required=False, label="Departman")

    class Meta:
        model = PropertyRole
        fields = ["name", "department", "permissions", "is_active"]


class UserPropertyAccessForm(HotelModelForm):
    pin = forms.CharField(
        required=False,
        min_length=4,
        max_length=8,
        strip=True,
        label="PIN",
        help_text="4–8 rakam. Yeni PIN girilmezse mevcut PIN korunur.",
        validators=[RegexValidator(r"^\d{4,8}$", "PIN yalnızca 4–8 rakamdan oluşmalıdır.")],
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password", "inputmode": "numeric", "pattern": "[0-9]{4,8}"}, render_value=False),
    )

    class Meta:
        model = UserPropertyAccess
        fields = ["user", "role", "is_active", "valid_from", "valid_until", "allowed_from_time", "allowed_until_time", "two_factor_required", "last_pin_change", "allowed_ip", "device_label", "purchase_approval_required", "bypass_price_control", "own_cash_only", "pos_access", "financial_access", "pin"]
        widgets = {
            "valid_from": forms.DateInput(attrs={"type": "date"}),
            "valid_until": forms.DateInput(attrs={"type": "date"}),
            "allowed_from_time": forms.TimeInput(attrs={"type": "time"}),
            "allowed_until_time": forms.TimeInput(attrs={"type": "time"}),
            "last_pin_change": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "allowed_ip": forms.TextInput(attrs={"autocomplete": "off", "inputmode": "numeric"}),
            "device_label": forms.TextInput(attrs={"autocomplete": "off"}),
        }


class UserPinChangeForm(forms.Form):
    pin = forms.CharField(
        min_length=4,
        max_length=8,
        label="Yeni PIN",
        validators=[RegexValidator(r"^\d{4,8}$", "PIN yalnızca 4–8 rakamdan oluşmalıdır.")],
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password", "inputmode": "numeric", "pattern": "[0-9]{4,8}"}),
    )
    pin_confirm = forms.CharField(
        min_length=4,
        max_length=8,
        label="PIN tekrar",
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password", "inputmode": "numeric", "pattern": "[0-9]{4,8}"}),
    )

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("pin") and cleaned.get("pin") != cleaned.get("pin_confirm"):
            self.add_error("pin_confirm", "PIN alanları aynı olmalıdır.")
        return cleaned


class UserProfileForm(HotelModelForm):
    class Meta:
        model = get_user_model()
        fields = ["name", "email", "phone", "gender", "position", "department"]
        widgets = {
            "gender": forms.TextInput(attrs={"placeholder": "Kadın / Erkek / Belirtmek istemiyor"}),
        }


class SupportTicketForm(HotelModelForm):
    class Meta:
        model = SupportTicket
        fields = ["module", "subject", "message", "attachment", "priority"]
        widgets = {"message": forms.Textarea(attrs={"rows": 5}), "attachment": forms.ClearableFileInput()}


class SupportReplyForm(HotelModelForm):
    class Meta:
        model = SupportTicketMessage
        fields = ["body", "is_internal"]
        widgets = {"body": forms.Textarea(attrs={"rows": 4})}


class SupportFAQCategoryForm(HotelModelForm):
    class Meta:
        model = SupportFAQCategory
        fields = ["name", "description", "order", "is_active"]


class SupportFAQItemForm(HotelModelForm):
    class Meta:
        model = SupportFAQItem
        fields = ["category", "question", "answer", "order", "is_active", "is_featured"]
        widgets = {"answer": forms.Textarea(attrs={"rows": 6})}


class SupportEducationRequestForm(HotelModelForm):
    class Meta:
        model = SupportEducationRequest
        fields = ["topic", "description", "priority", "contact_preference"]
        widgets = {"description": forms.Textarea(attrs={"rows": 5})}


class SupportReferralForm(HotelModelForm):
    class Meta:
        model = SupportReferral
        fields = ["business_name", "contact_name", "contact_email", "contact_phone", "message"]
        widgets = {"message": forms.Textarea(attrs={"rows": 4})}


class FrontOfficeCallRequestForm(HotelModelForm):
    class Meta:
        model = FrontOfficeCallRequest
        fields = ["name", "phone", "email", "note", "callback_at", "status"]
        widgets = {"note": forms.Textarea(attrs={"rows": 3}), "callback_at": forms.DateTimeInput(attrs={"type": "datetime-local"})}


class DepartmentDefinitionForm(HotelModelForm):
    class Meta:
        model = DepartmentDefinition
        fields = ["code", "name", "department_type", "default_revenue_code", "vat_percent", "pos_printer", "accounting_account", "is_active"]


class RevenueCodeForm(HotelModelForm):
    class Meta:
        model = RevenueCode
        fields = ["code", "name", "vat_percent", "is_active"]


class InvoiceForm(HotelModelForm):
    class Meta:
        model = Invoice
        exclude = ["property", "created_by", "lines"]
        widgets = {"issue_date": forms.DateInput(attrs={"type": "date"}), "due_date": forms.DateInput(attrs={"type": "date"}), "notes": forms.Textarea(attrs={"rows": 3})}


class PaymentGatewayForm(HotelModelForm):
    class Meta:
        model = PaymentGateway
        exclude = ["property"]


class AgencyForm(HotelModelForm):
    class Meta:
        model = Agency
        exclude = ["property"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}


class CurrencyDefinitionForm(HotelModelForm):
    class Meta:
        model = CurrencyDefinition
        exclude = ["property"]


class DailyCurrencyRateForm(HotelModelForm):
    class Meta:
        model = DailyCurrencyRate
        exclude = ["property"]
        widgets = {"rate_date": forms.DateInput(attrs={"type": "date"}), "valid_from": forms.DateTimeInput(attrs={"type": "datetime-local"}), "valid_until": forms.DateTimeInput(attrs={"type": "datetime-local"}), "synced_at": forms.DateTimeInput(attrs={"type": "datetime-local"})}


class VehicleForm(HotelModelForm):
    class Meta:
        model = Vehicle
        exclude = ["property"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 3}), "description": forms.Textarea(attrs={"rows": 3}), "model_year": forms.NumberInput(attrs={"min": 1900}), "door_count": forms.NumberInput(attrs={"min": 2}), "passenger_capacity": forms.NumberInput(attrs={"min": 1}), "minimum_driver_age": forms.NumberInput(attrs={"min": 18}), "minimum_license_months": forms.NumberInput(attrs={"min": 0})}


class VehiclePhotoForm(HotelModelForm):
    class Meta:
        model = VehiclePhoto
        fields = ["vehicle", "image", "alt_text", "is_primary", "sort_order", "show_online"]
        widgets = {"image": forms.ClearableFileInput(attrs={"accept": "image/*"})}

    def __init__(self, *args, property_=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["vehicle"].queryset = Vehicle.objects.filter(property=property_) if property_ else Vehicle.objects.none()


class ParkingLotForm(HotelModelForm):
    class Meta:
        model = ParkingLot
        exclude = ["property"]
        widgets = {
            "opening_time": forms.TimeInput(attrs={"type": "time"}),
            "closing_time": forms.TimeInput(attrs={"type": "time"}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }


class ParkingSpaceForm(HotelModelForm):
    class Meta:
        model = ParkingSpace
        fields = "__all__"
        widgets = {"notes": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, property_=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["parking_lot"].queryset = ParkingLot.objects.filter(property=property_) if property_ else ParkingLot.objects.none()


class VehicleRentalRateForm(HotelModelForm):
    class Meta:
        model = VehicleRentalRate
        exclude = []
        widgets = {
            "valid_from": forms.DateInput(attrs={"type": "date"}),
            "valid_until": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, property_=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["vehicle"].queryset = Vehicle.objects.filter(property=property_) if property_ else Vehicle.objects.none()


class RentalPricingRuleForm(HotelModelForm):
    class Meta:
        model = RentalPricingRule
        exclude = ["property"]
        widgets = {
            "valid_from": forms.DateInput(attrs={"type": "date"}),
            "valid_until": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }


class ParkingReservationForm(HotelModelForm):
    class Meta:
        model = ParkingReservation
        exclude = ["property", "confirmation_code", "created_by"]
        widgets = {
            "start_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "end_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, property_=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["parking_lot"].queryset = ParkingLot.objects.filter(property=property_) if property_ else ParkingLot.objects.none()
        self.fields["parking_space"].queryset = ParkingSpace.objects.filter(parking_lot__property=property_) if property_ else ParkingSpace.objects.none()
        self.fields["guest"].queryset = Guest.objects.filter(property=property_) if property_ else Guest.objects.none()
        self.fields["reservation"].queryset = Reservation.objects.filter(property=property_) if property_ else Reservation.objects.none()


class VehicleRentalBookingForm(HotelModelForm):
    insurance_package = forms.ChoiceField(required=False, choices=(), label="Sigorta paketi")
    extra_products = forms.MultipleChoiceField(required=False, choices=(), label="Ek ürünler", widget=forms.CheckboxSelectMultiple)

    class Meta:
        model = VehicleRentalBooking
        exclude = ["property", "confirmation_code", "created_by"]
        widgets = {
            "pickup_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "dropoff_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "remaining_payment_due": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "notes": forms.Textarea(attrs={"rows": 2}),
            "cancellation_policy": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, property_=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["vehicle"].queryset = Vehicle.objects.filter(property=property_) if property_ else Vehicle.objects.none()
        self.fields["rental_rate"].queryset = VehicleRentalRate.objects.filter(vehicle__property=property_) if property_ else VehicleRentalRate.objects.none()
        self.fields["guest"].queryset = Guest.objects.filter(property=property_) if property_ else Guest.objects.none()
        self.fields["reservation"].queryset = Reservation.objects.filter(property=property_) if property_ else Reservation.objects.none()
        self.fields["pickup_location_ref"].queryset = RentalLocation.objects.filter(property=property_, is_active=True) if property_ else RentalLocation.objects.none()
        self.fields["dropoff_location_ref"].queryset = RentalLocation.objects.filter(property=property_, is_active=True) if property_ else RentalLocation.objects.none()
        insurance_packages = RentalInsurancePackage.objects.filter(property=property_, is_active=True) if property_ else RentalInsurancePackage.objects.none()
        extras = RentalExtraProduct.objects.filter(property=property_, is_active=True) if property_ else RentalExtraProduct.objects.none()
        self.fields["insurance_package"].choices = [('', 'Sigorta seçilmedi')] + [(str(item.id), f"{item.name} · {item.price} {item.currency}") for item in insurance_packages]
        self.fields["extra_products"].choices = [(str(item.id), f"{item.name} · {item.price} {item.currency}") for item in extras]


class PublicParkingReservationForm(HotelModelForm):
    """Whitelist-only form for the public parking booking flow.

    Amount, status, payment and audit fields are deliberately not accepted
    from a browser. The server calculates the quote after validation.
    """

    class Meta:
        model = ParkingReservation
        fields = [
            "parking_lot", "parking_space", "customer_name", "customer_email",
            "customer_phone", "vehicle_plate", "start_at", "end_at", "notes",
        ]
        widgets = {
            "start_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "end_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, property_=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["parking_lot"].queryset = ParkingLot.objects.filter(
            property=property_, is_active=True, booking_enabled=True,
        ) if property_ else ParkingLot.objects.none()
        self.fields["parking_space"].queryset = ParkingSpace.objects.filter(
            parking_lot__property=property_, is_active=True,
        ) if property_ else ParkingSpace.objects.none()


class PublicRentalBookingForm(HotelModelForm):
    """Whitelist-only rental intake form; all prices remain server-owned."""

    privacy_consent = forms.BooleanField(required=True, label="Gizlilik ve veri saklama politikasını kabul ediyorum")
    marketing_consent = forms.BooleanField(required=False, label="Kampanya ve bilgilendirme mesajlarına izin veriyorum")

    insurance_package = forms.ChoiceField(required=False, choices=(), label="Sigorta paketi")
    extra_products = forms.MultipleChoiceField(required=False, choices=(), label="Ek ürünler", widget=forms.CheckboxSelectMultiple)

    class Meta:
        model = VehicleRentalBooking
        fields = [
            "vehicle", "rental_rate", "customer_name", "customer_email", "customer_phone",
            "pickup_location", "dropoff_location", "pickup_location_ref", "dropoff_location_ref",
            "pickup_at", "dropoff_at", "driver_age", "driver_license_country",
            "license_duration_months", "additional_driver_count", "promo_code",
            "corporate_code", "loyalty_code", "vehicle_class", "locale", "flight_number",
            "insurance_package", "extra_products", "notes",
        ]
        widgets = {
            "pickup_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "dropoff_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, property_=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["vehicle"].queryset = Vehicle.objects.filter(
            property=property_, is_active=True, online_enabled=True,
        ) if property_ else Vehicle.objects.none()
        self.fields["rental_rate"].queryset = VehicleRentalRate.objects.filter(
            vehicle__property=property_, vehicle__is_active=True,
            vehicle__online_enabled=True, is_active=True,
        ) if property_ else VehicleRentalRate.objects.none()
        self.fields["pickup_location_ref"].queryset = RentalLocation.objects.filter(
            property=property_, is_active=True,
        ) if property_ else RentalLocation.objects.none()
        self.fields["dropoff_location_ref"].queryset = RentalLocation.objects.filter(
            property=property_, is_active=True,
        ) if property_ else RentalLocation.objects.none()
        packages = RentalInsurancePackage.objects.filter(
            property=property_, is_active=True,
        ) if property_ else RentalInsurancePackage.objects.none()
        extras = RentalExtraProduct.objects.filter(
            property=property_, is_active=True,
        ) if property_ else RentalExtraProduct.objects.none()
        self.fields["insurance_package"].choices = [
            ("", "Sigorta seçilmedi"),
            *[(str(item.id), f"{item.name} · {item.price} {item.currency}") for item in packages],
        ]
        self.fields["extra_products"].choices = [
            (str(item.id), f"{item.name} · {item.price} {item.currency}") for item in extras
        ]


class RentalDriverProfileForm(HotelModelForm):
    class Meta:
        model = RentalDriverProfile
        exclude = ["property"]
        widgets = {
            "license_issued_at": forms.DateInput(attrs={"type": "date"}),
            "license_expires_at": forms.DateInput(attrs={"type": "date"}),
            "license_document": forms.ClearableFileInput(),
            "blacklist_reason": forms.Textarea(attrs={"rows": 2}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }


class RentalCancellationPolicyForm(HotelModelForm):
    class Meta:
        model = RentalCancellationPolicy
        exclude = ["property"]
        widgets = {"terms": forms.Textarea(attrs={"rows": 3})}


class RentalTaxRuleForm(HotelModelForm):
    class Meta:
        model = RentalTaxRule
        exclude = ["property"]


class RentalLocationForm(HotelModelForm):
    class Meta:
        model = RentalLocation
        exclude = ["property"]


class RentalChannelConnectionForm(HotelModelForm):
    class Meta:
        model = RentalChannelConnection
        exclude = ["property", "last_sync_at", "last_sync_status"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 2})}


class RentalChannelMappingForm(HotelModelForm):
    class Meta:
        model = RentalChannelMapping
        fields = "__all__"


class VehicleTelemetryEventForm(HotelModelForm):
    class Meta:
        model = VehicleTelemetryEvent
        exclude = ["property"]
        widgets = {"occurred_at": forms.DateTimeInput(attrs={"type": "datetime-local"})}


class RentalFlightStatusForm(HotelModelForm):
    class Meta:
        model = RentalFlightStatus
        fields = "__all__"
        widgets = {"scheduled_arrival_at": forms.DateTimeInput(attrs={"type": "datetime-local"}), "estimated_arrival_at": forms.DateTimeInput(attrs={"type": "datetime-local"}), "last_checked_at": forms.DateTimeInput(attrs={"type": "datetime-local"})}


class ParkingDeviceForm(HotelModelForm):
    class Meta:
        model = ParkingDevice
        exclude = ["property", "last_seen_at"]


class RentalExtraProductForm(HotelModelForm):
    class Meta:
        model = RentalExtraProduct
        exclude = ["property"]
        widgets = {"description": forms.Textarea(attrs={"rows": 2})}


class RentalInsurancePackageForm(HotelModelForm):
    class Meta:
        model = RentalInsurancePackage
        exclude = ["property"]
        widgets = {"coverage": forms.Textarea(attrs={"rows": 2})}


class RentalHandoverForm(HotelModelForm):
    class Meta:
        model = RentalHandover
        exclude = ["recorded_by"]
        widgets = {"recorded_at": forms.DateTimeInput(attrs={"type": "datetime-local"}), "damage_notes": forms.Textarea(attrs={"rows": 3}), "signature_file": forms.ClearableFileInput()}


class RentalHandoverPhotoForm(HotelModelForm):
    class Meta:
        model = RentalHandoverPhoto
        fields = "__all__"
        widgets = {"image": forms.ClearableFileInput(attrs={"accept": "image/*"})}


class RentalDamageCaseForm(HotelModelForm):
    class Meta:
        model = RentalDamageCase
        exclude = ["reference", "opened_at", "resolved_at"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}


class VehicleMaintenanceRecordForm(HotelModelForm):
    class Meta:
        model = VehicleMaintenanceRecord
        exclude = ["property"]
        widgets = {"scheduled_at": forms.DateInput(attrs={"type": "date"}), "completed_at": forms.DateInput(attrs={"type": "date"}), "notes": forms.Textarea(attrs={"rows": 2})}


class RentalFineForm(HotelModelForm):
    class Meta:
        model = RentalFine
        fields = "__all__"
        widgets = {"incurred_at": forms.DateTimeInput(attrs={"type": "datetime-local"}), "notes": forms.Textarea(attrs={"rows": 2})}


class ParkingSubscriptionForm(HotelModelForm):
    class Meta:
        model = ParkingSubscription
        fields = "__all__"
        widgets = {"valid_from": forms.DateTimeInput(attrs={"type": "datetime-local"}), "valid_until": forms.DateTimeInput(attrs={"type": "datetime-local"})}


class ParkingAccessEventForm(HotelModelForm):
    class Meta:
        model = ParkingAccessEvent
        fields = "__all__"
        widgets = {"occurred_at": forms.DateTimeInput(attrs={"type": "datetime-local"})}


class ParkingValetRecordForm(HotelModelForm):
    class Meta:
        model = ParkingValetRecord
        fields = "__all__"
        widgets = {"received_at": forms.DateTimeInput(attrs={"type": "datetime-local"}), "returned_at": forms.DateTimeInput(attrs={"type": "datetime-local"}), "notes": forms.Textarea(attrs={"rows": 2})}


class ParkingPenaltyForm(HotelModelForm):
    class Meta:
        model = ParkingPenalty
        fields = "__all__"
        widgets = {"issued_at": forms.DateTimeInput(attrs={"type": "datetime-local"}), "notes": forms.Textarea(attrs={"rows": 2})}


class RentalContractForm(HotelModelForm):
    class Meta:
        model = RentalContract
        fields = "__all__"
        widgets = {"terms": forms.Textarea(attrs={"rows": 5}), "signed_at": forms.DateTimeInput(attrs={"type": "datetime-local"}), "signature_file": forms.ClearableFileInput(), "document_file": forms.ClearableFileInput()}


class RentalPaymentForm(HotelModelForm):
    class Meta:
        model = RentalPayment
        fields = "__all__"


class RentalInvoiceForm(HotelModelForm):
    class Meta:
        model = RentalInvoice
        fields = "__all__"


class CashierShiftForm(HotelModelForm):
    class Meta:
        model = CashierShift
        exclude = ["property", "cashier", "opened_at", "closed_at", "closed_by", "variance", "status"]
        widgets = {"closing_note": forms.Textarea(attrs={"rows": 3})}


class FrontCashTransactionForm(HotelModelForm):
    class Meta:
        model = FrontCashTransaction
        exclude = ["property", "posted_by", "posted_at", "is_voided"]
        widgets = {"description": forms.TextInput(attrs={"placeholder": "İşlem açıklaması"})}

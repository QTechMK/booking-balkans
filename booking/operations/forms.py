from django import forms
from django.core.validators import RegexValidator
from django.contrib.auth import get_user_model

from booking.tenancy.models import (
    BedType, BoardType, Property, PropertySettings, RateType, RoomGroup, RoomLocation, RoomPhoto, RoomView, Unit, UnitType,
)
from .models import AccessPermission, DepartmentDefinition, FrontOfficeCallRequest, GuestProfileExtension, GuestSegment, LoyaltyTier, MarketingCampaign, MessageTemplate, OperationalTask, PropertyRole, PropertyService, RevenueCode, SupportEducationRequest, SupportFAQCategory, SupportFAQItem, SupportReferral, SupportTicket, SupportTicketMessage, TaskGroup, TaskLocation, UserPropertyAccess


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
        fields = ["code", "name", "department_type", "default_revenue_code", "is_active"]


class RevenueCodeForm(HotelModelForm):
    class Meta:
        model = RevenueCode
        fields = ["code", "name", "vat_percent", "is_active"]

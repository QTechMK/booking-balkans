from django import forms

from booking.tenancy.models import (
    BedType, BoardType, Property, PropertySettings, RateType, RoomGroup, RoomLocation, RoomPhoto, RoomView, Unit, UnitType,
)
from .models import GuestProfileExtension, GuestSegment, LoyaltyTier, MarketingCampaign, MessageTemplate, OperationalTask, TaskGroup, TaskLocation


class PropertySettingsForm(forms.ModelForm):
    class Meta:
        model = PropertySettings
        exclude = ["property"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}


class PropertyProfileForm(forms.ModelForm):
    class Meta:
        model = Property
        fields = ["name", "slug", "business_type", "address", "city", "country", "document_number", "timezone", "currency", "is_active"]
        widgets = {"address": forms.Textarea(attrs={"rows": 2})}


class DictionaryForm(forms.ModelForm):
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


class RateTypeForm(DictionaryForm):
    class Meta(DictionaryForm.Meta):
        model = RateType
        fields = DictionaryForm.Meta.fields + [
            "is_refundable", "prepayment_percent", "price_factor", "cancellation_until_hours",
            "cancellation_penalty_days", "min_nights", "max_nights", "show_online",
        ]


class RoomPhotoForm(forms.ModelForm):
    class Meta:
        model = RoomPhoto
        fields = ["unit_type", "unit", "image_url", "alt_text", "is_primary", "sort_order"]

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("unit_type") and not cleaned.get("unit"):
            raise forms.ValidationError("Fotoğraf bir oda tipine veya fiziksel odaya bağlanmalıdır.")
        return cleaned


class TaskDictionaryForm(forms.ModelForm):
    class Meta:
        fields = ["code", "name", "is_active"]


class TaskGroupForm(TaskDictionaryForm):
    class Meta(TaskDictionaryForm.Meta):
        model = TaskGroup


class TaskLocationForm(TaskDictionaryForm):
    class Meta(TaskDictionaryForm.Meta):
        model = TaskLocation


class OperationalTaskForm(forms.ModelForm):
    class Meta:
        model = OperationalTask
        fields = ["group", "location", "unit", "title", "description", "status", "priority", "assigned_to", "due_at"]
        widgets = {"due_at": forms.DateTimeInput(attrs={"type": "datetime-local"}), "description": forms.Textarea(attrs={"rows": 2})}


class GuestProfileForm(forms.ModelForm):
    class Meta:
        model = GuestProfileExtension
        fields = ["gender", "birth_date", "nationality", "identity_reference", "company_name", "tax_number", "vip", "gdpr_confirmed", "email_confirmed", "phone_confirmed", "preferences", "allergens", "loyalty_code"]
        widgets = {"birth_date": forms.DateInput(attrs={"type": "date"}), "preferences": forms.Textarea(attrs={"rows": 2}), "allergens": forms.Textarea(attrs={"rows": 2})}


class LoyaltyTierForm(forms.ModelForm):
    class Meta:
        model = LoyaltyTier
        fields = ["code", "name", "minimum_points", "discount_percent", "is_active"]


class UnitTypeForm(forms.ModelForm):
    class Meta:
        model = UnitType
        exclude = ["property", "created_at", "updated_at"]
        widgets = {"description": forms.Textarea(attrs={"rows": 2})}


class UnitForm(forms.ModelForm):
    class Meta:
        model = Unit
        exclude = ["property", "created_at", "updated_at"]
        widgets = {"description": forms.Textarea(attrs={"rows": 2})}


class GuestSegmentForm(forms.ModelForm):
    class Meta:
        model = GuestSegment
        exclude = ["property", "criteria", "created_at", "updated_at"]
        widgets = {"description": forms.Textarea(attrs={"rows": 2})}


class MessageTemplateForm(forms.ModelForm):
    class Meta:
        model = MessageTemplate
        exclude = ["property", "updated_at"]
        widgets = {"body": forms.Textarea(attrs={"rows": 5})}


class MarketingCampaignForm(forms.ModelForm):
    class Meta:
        model = MarketingCampaign
        exclude = ["property", "sent_at", "created_by", "created_at"]
        widgets = {"scheduled_at": forms.DateTimeInput(attrs={"type": "datetime-local"})}

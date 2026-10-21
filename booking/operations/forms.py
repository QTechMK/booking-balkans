from django import forms

from booking.tenancy.models import (
    BedType, BoardType, PropertySettings, RateType, RoomGroup, RoomLocation, RoomView,
)


class PropertySettingsForm(forms.ModelForm):
    class Meta:
        model = PropertySettings
        exclude = ["property"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}


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

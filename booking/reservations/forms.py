from django import forms

from .models import Guest


class BookingSearchForm(forms.Form):
    property_id = forms.IntegerField(widget=forms.HiddenInput)
    rate_plan_id = forms.IntegerField(widget=forms.HiddenInput)
    check_in = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    check_out = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    quantity = forms.IntegerField(
        min_value=1,
        initial=1,
        error_messages={"min_value": "Quantity must be positive."},
    )

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("check_in") and cleaned.get("check_out"):
            if cleaned["check_out"] <= cleaned["check_in"]:
                self.add_error("check_out", "Check-out must be after check-in.")
        return cleaned


class GuestBookingForm(forms.ModelForm):
    class Meta:
        model = Guest
        fields = ["first_name", "last_name", "email", "phone", "country"]
        widgets = {
            "first_name": forms.TextInput(attrs={"autocomplete": "given-name"}),
            "last_name": forms.TextInput(attrs={"autocomplete": "family-name"}),
            "email": forms.EmailInput(attrs={"autocomplete": "email"}),
            "phone": forms.TextInput(attrs={"autocomplete": "tel"}),
            "country": forms.TextInput(attrs={"maxlength": 2, "placeholder": "TR"}),
        }

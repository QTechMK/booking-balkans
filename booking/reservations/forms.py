from django import forms

from .models import Guest


class MarketplaceSearchForm(forms.Form):
    q = forms.CharField(required=False, label="Konum veya işletme")
    check_in = forms.DateField(
        label="Giriş",
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}),
    )
    check_out = forms.DateField(
        label="Çıkış",
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}),
    )
    quantity = forms.IntegerField(
        label="Oda",
        min_value=1,
        initial=1,
        widget=forms.NumberInput(attrs={"class": "form-control", "min": 1}),
    )

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("check_in") and cleaned.get("check_out"):
            if cleaned["check_out"] <= cleaned["check_in"]:
                self.add_error("check_out", "Çıkış tarihi giriş tarihinden sonra olmalı.")
        return cleaned


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
            "first_name": forms.TextInput(attrs={"class": "form-control", "autocomplete": "given-name"}),
            "last_name": forms.TextInput(attrs={"class": "form-control", "autocomplete": "family-name"}),
            "email": forms.EmailInput(attrs={"class": "form-control", "autocomplete": "email"}),
            "phone": forms.TextInput(attrs={"class": "form-control", "autocomplete": "tel"}),
            "country": forms.TextInput(attrs={"class": "form-control", "maxlength": 2, "placeholder": "TR"}),
        }
        labels = {
            "first_name": "Ad",
            "last_name": "Soyad",
            "email": "E-posta",
            "phone": "Telefon",
            "country": "Ülke kodu",
        }

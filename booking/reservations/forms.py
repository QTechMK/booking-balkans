from django import forms

from .models import Guest
from .models import ReservationChannel
from booking.tenancy.models import Property
from booking.tenancy.models import DailyRate
from booking.tenancy.models import Inventory
from booking.tenancy.models import RatePlan
from booking.tenancy.models import Unit
from booking.tenancy.models import UnitType


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


class ReservationChannelForm(forms.ModelForm):
    class Meta:
        model = ReservationChannel
        fields = [
            "name",
            "code",
            "source",
            "website_name",
            "website_url",
            "website_domain",
            "sort_order",
            "is_active",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "code": forms.TextInput(attrs={"class": "form-control", "placeholder": "ornek-kanal"}),
            "source": forms.Select(attrs={"class": "form-select"}),
            "website_name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Örn. Hotel resmi sitesi"}),
            "website_url": forms.URLInput(attrs={"class": "form-control", "placeholder": "https://example.com"}),
            "website_domain": forms.TextInput(attrs={"class": "form-control", "placeholder": "example.com"}),
            "sort_order": forms.NumberInput(attrs={"class": "form-control", "min": 0}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }
        labels = {
            "name": "Kanal adı",
            "code": "Kanal kodu",
            "source": "Kaynak grubu",
            "website_name": "Website adı",
            "website_url": "Website URL",
            "website_domain": "Website domain/origin",
            "sort_order": "Sıra",
            "is_active": "Aktif",
        }

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("source") == "widget":
            if not cleaned.get("website_name"):
                self.add_error("website_name", "Widget kanalı için website adı gereklidir.")
            if not cleaned.get("website_domain"):
                self.add_error("website_domain", "Widget kanalı için website domaini gereklidir.")
        return cleaned


class BusinessManualReservationForm(forms.Form):
    property = forms.ModelChoiceField(queryset=Property.objects.none(), label="Tesis")
    rate_plan = forms.ModelChoiceField(queryset=RatePlan.objects.none(), label="Rate plan")
    channel = forms.ModelChoiceField(queryset=ReservationChannel.objects.none(), label="Rezervasyon kanalı")
    check_in = forms.DateField(label="Giriş", widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}))
    check_out = forms.DateField(label="Çıkış", widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}))
    quantity = forms.IntegerField(label="Oda/ünite", min_value=1, initial=1, widget=forms.NumberInput(attrs={"class": "form-control", "min": 1}))
    first_name = forms.CharField(label="Ad", max_length=120, widget=forms.TextInput(attrs={"class": "form-control"}))
    last_name = forms.CharField(label="Soyad", required=False, max_length=120, widget=forms.TextInput(attrs={"class": "form-control"}))
    email = forms.EmailField(label="E-posta", required=False, widget=forms.EmailInput(attrs={"class": "form-control"}))
    phone = forms.CharField(label="Telefon", required=False, max_length=40, widget=forms.TextInput(attrs={"class": "form-control"}))
    country = forms.CharField(label="Ülke kodu", required=False, max_length=2, initial="TR", widget=forms.TextInput(attrs={"class": "form-control", "maxlength": 2}))

    def __init__(self, *args, properties, selected_property=None, **kwargs):
        super().__init__(*args, **kwargs)
        properties = properties.filter(is_active=True).order_by("name")
        self.fields["property"].queryset = properties
        if selected_property:
            self.fields["property"].initial = selected_property
            self.fields["rate_plan"].queryset = selected_property.rate_plans.filter(is_active=True).order_by("name")
            self.fields["channel"].queryset = selected_property.reservation_channels.filter(is_active=True)

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("check_in") and cleaned.get("check_out") and cleaned["check_out"] <= cleaned["check_in"]:
            self.add_error("check_out", "Çıkış tarihi giriş tarihinden sonra olmalı.")
        if cleaned.get("property"):
            property_ = cleaned["property"]
            if cleaned.get("rate_plan") and cleaned["rate_plan"].property_id != property_.id:
                self.add_error("rate_plan", "Rate plan seçilen tesise ait değil.")
            if cleaned.get("channel") and cleaned["channel"].property_id != property_.id:
                self.add_error("channel", "Kanal seçilen tesise ait değil.")
        return cleaned


class BusinessUnitTypeForm(forms.ModelForm):
    class Meta:
        model = UnitType
        fields = ["name", "code", "kind", "inventory_mode", "capacity_per_unit", "max_adults", "max_children", "is_active"]
        widgets = {field: forms.Select(attrs={"class": "form-select"}) for field in ["kind", "inventory_mode"]}


class BusinessUnitForm(forms.ModelForm):
    class Meta:
        model = Unit
        fields = ["unit_type", "code", "name", "status", "floor", "is_active"]
        widgets = {"unit_type": forms.Select(attrs={"class": "form-select"}), "status": forms.Select(attrs={"class": "form-select"})}


class BusinessRatePlanForm(forms.ModelForm):
    class Meta:
        model = RatePlan
        fields = ["unit_type", "name", "code", "meal_plan", "cancellation_policy", "is_refundable", "max_adults", "max_children", "currency", "is_active"]
        widgets = {field: forms.Select(attrs={"class": "form-select"}) for field in ["unit_type", "meal_plan"]}


class BusinessDailyRateForm(forms.ModelForm):
    class Meta:
        model = DailyRate
        fields = ["rate_plan", "date", "amount", "min_nights", "max_nights", "is_closed"]
        widgets = {
            "rate_plan": forms.Select(attrs={"class": "form-select"}),
            "date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "amount": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0"}),
            "min_nights": forms.NumberInput(attrs={"class": "form-control", "min": "1"}),
            "max_nights": forms.NumberInput(attrs={"class": "form-control", "min": "1"}),
            "is_closed": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


class BusinessInventoryForm(forms.ModelForm):
    class Meta:
        model = Inventory
        fields = ["unit_type", "date", "total_capacity", "blocked_capacity", "is_closed"]
        widgets = {
            "unit_type": forms.Select(attrs={"class": "form-select"}),
            "date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "total_capacity": forms.NumberInput(attrs={"class": "form-control", "min": "0"}),
            "blocked_capacity": forms.NumberInput(attrs={"class": "form-control", "min": "0"}),
            "is_closed": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


class BusinessBulkDailyRateForm(forms.Form):
    rate_plan = forms.ModelChoiceField(queryset=RatePlan.objects.none(), label="Rate plan")
    start_date = forms.DateField(label="Başlangıç", widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}))
    end_date = forms.DateField(label="Bitiş", widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}))
    amount = forms.DecimalField(label="Tutar", min_value=0, max_digits=12, decimal_places=2, widget=forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0"}))
    min_nights = forms.IntegerField(label="Minimum gece", min_value=1, initial=1, widget=forms.NumberInput(attrs={"class": "form-control", "min": 1}))
    max_nights = forms.IntegerField(label="Maksimum gece", min_value=1, required=False, widget=forms.NumberInput(attrs={"class": "form-control", "min": 1}))
    is_closed = forms.BooleanField(label="Satışa kapalı", required=False, widget=forms.CheckboxInput(attrs={"class": "form-check-input"}))

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("start_date") and cleaned.get("end_date") and cleaned["end_date"] < cleaned["start_date"]:
            self.add_error("end_date", "Bitiş tarihi başlangıç tarihinden önce olamaz.")
        if cleaned.get("max_nights") and cleaned.get("min_nights") and cleaned["max_nights"] < cleaned["min_nights"]:
            self.add_error("max_nights", "Maksimum gece minimum geceden küçük olamaz.")
        return cleaned


class BusinessBulkInventoryForm(forms.Form):
    unit_type = forms.ModelChoiceField(queryset=UnitType.objects.none(), label="Ünite tipi")
    start_date = forms.DateField(label="Başlangıç", widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}))
    end_date = forms.DateField(label="Bitiş", widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}))
    total_capacity = forms.IntegerField(label="Toplam kapasite", min_value=0, widget=forms.NumberInput(attrs={"class": "form-control", "min": 0}))
    blocked_capacity = forms.IntegerField(label="Bloke kapasite", min_value=0, initial=0, widget=forms.NumberInput(attrs={"class": "form-control", "min": 0}))
    is_closed = forms.BooleanField(label="Satışa kapalı", required=False, widget=forms.CheckboxInput(attrs={"class": "form-check-input"}))

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("start_date") and cleaned.get("end_date") and cleaned["end_date"] < cleaned["start_date"]:
            self.add_error("end_date", "Bitiş tarihi başlangıç tarihinden önce olamaz.")
        if cleaned.get("blocked_capacity") is not None and cleaned.get("total_capacity") is not None and cleaned["blocked_capacity"] > cleaned["total_capacity"]:
            self.add_error("blocked_capacity", "Bloke kapasite toplam kapasiteyi aşamaz.")
        return cleaned

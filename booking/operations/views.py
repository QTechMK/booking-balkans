import hashlib
import hmac
import json
from datetime import timedelta
from urllib.parse import urlparse

from django.conf import settings as django_settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.core.exceptions import ValidationError
from django.core.files.storage import default_storage
from django.db import transaction
from django.db.models import Q, Sum
from django.db.models import BooleanField
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.http import QueryDict
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.clickjacking import xframe_options_exempt
from allauth.mfa.models import Authenticator
from allauth.mfa.utils import is_mfa_enabled

from booking import __version__
from booking.reservations.models import Guest, Reservation, ReservationItem, ReservationStatus, StayStatus
from booking.reservations.views import _business_properties
from booking.tenancy.models import (
    BedType, BoardType, HotelPhoto, Membership, Property, PropertySettings, RateType,
    RoomGroup, RoomLocation, RoomPhoto, RoomView, Unit, UnitType, Vehicle, VehiclePhoto, PropertyModuleLicense,
)

from .models import (
    GuestProfileExtension,
    HousekeepingStatus,
    HousekeepingTask,
    HousekeepingTaskHistory,
    MaintenanceStatus,
    MaintenanceTicket,
    MaintenanceTicketHistory,
    OnlineBookingSettings,
    AccessPermission, GuestLoyaltyAccount, GuestProfileExtension, GuestSegment, LoyaltyTier, LoyaltyTransaction, MarketingCampaign, MarketingDelivery, MessageTemplate, OperationalTask, ParkingAccessEvent, ParkingLot, ParkingPenalty, ParkingReservation, ParkingSpace, ParkingSubscription, ParkingValetRecord, PropertyService, RentalAuditEvent, RentalCancellationPolicy, RentalContract, RentalDamageCase, RentalDriverProfile, RentalExtraProduct, RentalFine, RentalHandover, RentalHandoverPhoto, RentalInsurancePackage, RentalInvoice, RentalLocation, RentalPayment, RentalTaxRule, ServiceRequest, VehicleMaintenanceRecord, VehicleRentalBooking, VehicleRentalRate,
    PropertyRole,
    TaskPriority,
    TaskGroup,
    TaskLocation,
    TaskStatus, UserAccessLog, UserPropertyAccess, Agency, CashierShift, CurrencyDefinition, DailyCurrencyRate, DepartmentDefinition, FrontCashTransaction, FrontOfficeCallRequest, Invoice, NightAuditRun, PaymentGateway, RevenueCode, SupportAuditEvent, SupportEducationRequest, SupportFAQCategory, SupportFAQItem, SupportHelpLink, SupportReferral, SupportTicket, SupportTicketMessage, SupportVideoCategory, ParkingDevice, RentalChannelConnection, RentalChannelMapping, RentalChannelSyncEvent, RentalDataRequest, RentalFlightStatus, RentalNotification, RentalPrivacyEvent, RentalPricingRule, VehicleTelemetryEvent, WebhookEvent,
    UnitHousekeepingState,
)
from .forms import (
    BedTypeForm, BoardTypeForm, DEPARTMENT_CHOICES, PropertyProfileForm, PropertySettingsForm, RateTypeForm,
    AgencyForm, CashierShiftForm, CurrencyDefinitionForm, DailyCurrencyRateForm, DepartmentDefinitionForm, FrontCashTransactionForm, FrontOfficeCallRequestForm, GuestProfileForm, GuestSegmentForm, HotelPhotoForm, InvoiceForm, LoyaltyTierForm, MarketingCampaignForm, MessageTemplateForm, OperationalTaskForm, ParkingAccessEventForm, ParkingDeviceForm, ParkingLotForm, ParkingPenaltyForm, ParkingReservationForm, ParkingSpaceForm, ParkingSubscriptionForm, ParkingValetRecordForm, PaymentGatewayForm, PropertyRoleForm, PropertyServiceForm, PublicParkingReservationForm, PublicRentalBookingForm, RentalCancellationPolicyForm, RentalChannelConnectionForm, RentalChannelMappingForm, RentalContractForm, RentalDamageCaseForm, RentalDriverProfileForm, RentalExtraProductForm, RentalFineForm, RentalFlightStatusForm, RentalHandoverForm, RentalHandoverPhotoForm, RentalInsurancePackageForm, RentalInvoiceForm, RentalLocationForm, RentalPaymentForm, RentalPricingRuleForm, RentalTaxRuleForm, RevenueCodeForm, RoomGroupForm, RoomLocationForm, RoomPhotoForm, RoomViewForm, SupportEducationRequestForm, SupportReferralForm, SupportReplyForm, SupportTicketForm, TaskGroupForm, TaskLocationForm, UnitForm, UnitTypeForm, UserPinChangeForm, UserPropertyAccessForm, UserProfileForm, VehicleForm, VehiclePhotoForm, VehicleMaintenanceRecordForm, VehicleRentalBookingForm, VehicleRentalRateForm, VehicleTelemetryEventForm,
)
from .services.rental_pricing import available_parking_spaces, available_rental_vehicles, calculate_parking_quote, calculate_rental_quote
from .services.rental_notifications import queue_rental_notifications
from .services.rental_payments import create_pending_rental_payment
from .services.rental_checkout import start_rental_checkout
from .services.rental_payment_actions import capture_rental_payment, record_manual_bank_refund, refund_rental_payment
from .services.fleet_reservations import save_parking_reservation, save_rental_booking
from .services.rental_settlement import issue_settlement_invoice, upsert_rental_settlement
from .services.rental_channels import queue_first_party_reservation_event, queue_property_first_party_event
from booking.reservations.services.payments import PaymentConfigurationError, PaymentProviderError
from booking.reservations.services.bank_payments import (
    render_checkout, verify_cpay_response, verify_nestpay_response,
)


def _selected_property(request):
    properties = _business_properties(request.user).order_by("name")
    property_id = request.POST.get("property_id") or request.GET.get("property_id")
    selected = properties.filter(id=property_id).first() if property_id else None
    return properties, selected or properties.first()


def _users_for_property(property_):
    if not property_:
        return []
    return Membership.objects.filter(
        Q(organization=property_.organization, property__isnull=True)
        | Q(property=property_), is_active=True
    ).select_related("user").values_list("user", "user__username")


def _has_operation_permission(request, property_, code):
    if not property_ or request.user.is_superuser:
        return True
    explicit = UserPropertyAccess.objects.filter(
        user=request.user, property=property_, is_active=True,
        role__is_active=True,
    ).filter(Q(valid_from__isnull=True) | Q(valid_from__lte=timezone.localdate())) \
      .filter(Q(valid_until__isnull=True) | Q(valid_until__gte=timezone.localdate()))
    if explicit.exists():
        return explicit.filter(role__permissions__code=code, role__permissions__is_active=True).exists()
    return Membership.objects.filter(
        user=request.user, organization=property_.organization, is_active=True,
    ).filter(Q(property__isnull=True) | Q(property=property_)).exists()


def _permission_denied(request, property_, code):
    return bool(property_ and not _has_operation_permission(request, property_, code))


def _module_license_denied(request, property_, module):
    """Enforce independently sellable modules while preserving legacy tenants."""
    if not property_ or request.user.is_superuser:
        return False
    licenses = PropertyModuleLicense.objects.filter(property=property_)
    if not licenses.exists():
        return False
    license_row = licenses.filter(module=module).first()
    return not license_row or not license_row.is_current()


def _support_context(request):
    properties, selected = _selected_property(request)
    if _permission_denied(request, selected, "operations.support.manage"):
        return properties, selected, True
    return properties, selected, False


# ElektraWeb uyumluluk kataloğunda ekranı tanımlanmış, ancak iş akışı henüz
# geliştirilmemiş ekranlar. Her kayıt gerçek bir URL alır; ortak ekran kabuğu
# daha sonraki sprintlerde ilgili forma veya listeye dönüştürülebilir.
PLANNED_SCREENS = {
    "quick_setup": {"module": "setup", "module_label": "SETUP", "label": "Quick Setup", "title": "Quick Setup", "description": "Tesis kurulum sihirbazı."},
    "hotel_settings_menu": {"module": "setup", "module_label": "SETUP", "label": "Hotel Settings Menu", "title": "Hotel Settings Menu", "description": "Otel tanım ekranlarının klasör yapısı."},
    "agency_panel": {"module": "setup", "module_label": "SETUP", "label": "ElektraHotels.com Agency Panel", "title": "ElektraHotels.com Agency Panel", "description": "ElektraHotels.com acente paneli bağlantısı."},
    "giata_drive": {"module": "setup", "module_label": "SETUP", "label": "Giata Drive", "title": "Giata Drive", "description": "Giata tesis ve oda verisi senkronizasyonu."},
    "licence_info": {"module": "setup", "module_label": "SETUP", "label": "Licence Info", "title": "Licence Info", "description": "Lisans ve modül kullanım bilgileri."},
    "selected_modules": {"module": "setup", "module_label": "SETUP", "label": "Selected Modules", "title": "Selected Modules", "description": "Tesis için etkinleştirilen modüller."},
    "questions": {"module": "setup", "module_label": "SETUP", "label": "Questions", "title": "Questions", "description": "Kurulum ve operasyon soru tanımları."},
    "contact_us": {"module": "setup", "module_label": "SETUP", "label": "Contact Us", "title": "Contact Us", "description": "Destek ekibiyle iletişim kanalları."},
    "manager_support_form": {"module": "setup", "module_label": "SETUP", "label": "Manager Support Form", "title": "Manager Support Form", "description": "Otel yöneticisi destek formu."},
    "correction_form": {"module": "setup", "module_label": "SETUP", "label": "Correction Form", "title": "Correction Form", "description": "Veri ve tanım düzeltme talebi formu."},
    "carbon_certificate": {"module": "setup", "module_label": "SETUP", "label": "Carbon Certificate", "title": "Carbon Certificate", "description": "Karbon sertifikası ve sürdürülebilirlik kayıtları."},
    "mobile_app": {"module": "mobile_app", "module_label": "MOBILE APP", "label": "Mobile App", "title": "Mobile App", "description": "Mobil uygulama ekranları ve tesis mobil operasyonları."},

    "front_office_status": {"module": "front_office", "module_label": "FRONT OFFICE", "label": "Status", "title": "Front Office Status", "description": "Ön büro operasyon durumları ve hızlı filtreler."},
    "group_reservations": {"module": "front_office", "module_label": "FRONT OFFICE", "label": "Group Reservations", "title": "Group Reservations", "description": "Grup rezervasyonu ve grup konaklama yönetimi."},
    "tour_operator_integrations": {"module": "front_office", "module_label": "FRONT OFFICE", "label": "Tour Operator Integrations", "title": "Tour Operator Integrations", "description": "Tur operatörü entegrasyonları."},
    "room_type_availability": {"module": "front_office", "module_label": "FRONT OFFICE", "label": "Room Type Availability", "title": "Room Type Availability", "description": "Oda tipi bazında müsaitlik görünümü."},
    "available_rooms": {"module": "front_office", "module_label": "FRONT OFFICE", "label": "Available Rooms", "title": "Available Rooms", "description": "Tarih ve oda tipi bazında müsait odalar."},
    "quick_room_assignment": {"module": "front_office", "module_label": "FRONT OFFICE", "label": "Quick Room Assignment", "title": "Quick Room Assignment", "description": "Rezervasyona hızlı oda atama ekranı."},
    "quick_posting": {"module": "front_office", "module_label": "FRONT OFFICE", "label": "Quick Posting", "title": "Quick Posting", "description": "Folyoya hızlı işlem gönderme ekranı."},
    "folio_balances": {"module": "front_office", "module_label": "FRONT OFFICE", "label": "Reservation Folio Balances", "title": "Reservation Folio Balances", "description": "Rezervasyonların açık folyo bakiyeleri."},
    "front_cash": {"module": "front_cash", "module_label": "FRONT CASH", "label": "Front Cash", "title": "Front Cash", "description": "Ön kasa tahsilat ve kasa hareketleri."},
    "credit_accounts": {"module": "front_office", "module_label": "FRONT OFFICE", "label": "Credit Accounts", "title": "Credit Accounts", "description": "Kredili cari hesaplar ve limitleri."},
    "daily_currency_rates": {"module": "front_office", "module_label": "FRONT OFFICE", "label": "Daily Currency Rates & Entry", "title": "Daily Currency Rates & Entry", "description": "Günlük döviz kurları ve kur girişi."},
    "folio_routing": {"module": "front_office", "module_label": "FRONT OFFICE", "label": "Folio Routing List", "title": "Folio Routing List", "description": "Folio yönlendirme kuralları."},
    "guest_cards": {"module": "front_office", "module_label": "FRONT OFFICE", "label": "Guest Cards", "title": "Guest Cards", "description": "Ayrıntılı misafir kartı, belgeler ve konaklama geçmişi."},
    "guest_medical_daily": {"module": "front_office", "module_label": "FRONT OFFICE", "label": "Guest Medical Daily List", "title": "Guest Medical Daily List", "description": "Yetkili kullanıcılar için günlük misafir sağlık kayıtları."},
    "closed_room_list": {"module": "front_office", "module_label": "FRONT OFFICE", "label": "Closed Room List", "title": "Closed Room List", "description": "Satışa ve kullanıma kapalı oda listesi."},
    "lost_and_found": {"module": "front_office", "module_label": "FRONT OFFICE", "label": "Lost and Found", "title": "Lost and Found", "description": "Kayıp eşya kayıt ve teslim süreci."},
    "hotel_phone_book": {"module": "front_office", "module_label": "FRONT OFFICE", "label": "Hotel Phone Book", "title": "Hotel Phone Book", "description": "Otel dahili ve iletişim rehberi."},
    "police_lists": {"module": "front_office", "module_label": "FRONT OFFICE", "label": "Police Lists", "title": "Police Lists", "description": "Yetkili makamlara yönelik konaklama listeleri."},
    "offline_backup": {"module": "front_office", "module_label": "FRONT OFFICE", "label": "Offline Backup", "title": "Offline Backup", "description": "Çevrimdışı yedek ve geri yükleme işlemleri."},
    "park_entry": {"module": "front_office", "module_label": "FRONT OFFICE", "label": "Park Entry", "title": "Park Entry", "description": "Otopark giriş ve çıkış kayıtları."},

    "archived_end_of_day_reports": {"module": "night_audit", "module_label": "NIGHT AUDIT", "label": "Archived End Of Day Reports", "title": "Archived End Of Day Reports", "description": "Arşivlenmiş gün sonu raporları."},
    "night_audit_html_reports": {"module": "night_audit", "module_label": "NIGHT AUDIT", "label": "Night Audit HTML Reports", "title": "Night Audit HTML Reports", "description": "Night Audit HTML raporları."},
    "end_of_year": {"module": "night_audit", "module_label": "NIGHT AUDIT", "label": "End Of Year", "title": "End Of Year", "description": "Yıl sonu kapanış ve devir işlemleri."},
    "end_of_day_log_2": {"module": "night_audit", "module_label": "NIGHT AUDIT", "label": "End of The Day Log 2", "title": "End of The Day Log 2", "description": "İkinci gün sonu işlem log görünümü."},
    "reservation_updates": {"module": "night_audit", "module_label": "NIGHT AUDIT", "label": "Reservation Updates", "title": "Reservation Updates", "description": "Gün sonu sırasında oluşan rezervasyon değişiklikleri."},

    "all_invoices": {"module": "invoice", "module_label": "INVOICE", "label": "All Invoices", "title": "All Invoices", "description": "Tüm fatura türlerinin birleşik görünümü."},
    "mustahsil": {"module": "invoice", "module_label": "INVOICE", "label": "Mustahsil", "title": "Mustahsil", "description": "Müstahsil makbuzu kayıtları."},
    "all_accounts": {"module": "invoice", "module_label": "INVOICE", "label": "All Accounts", "title": "All Accounts", "description": "Fatura cari hesapları."},
    "sales_price_agreements": {"module": "invoice", "module_label": "INVOICE", "label": "Sales Price Agreements", "title": "Sales Price Agreements", "description": "Satış fiyat anlaşmaları."},
    "invoice_bulk_control": {"module": "invoice", "module_label": "INVOICE", "label": "Invoice Control and Bulk Create", "title": "Invoice Control and Bulk Create", "description": "Fatura kontrolü ve toplu fatura oluşturma."},
    "proforma_invoice_list": {"module": "invoice", "module_label": "INVOICE", "label": "Proforma Invoice List", "title": "Proforma Invoice List", "description": "Proforma fatura listesi."},
    "proforma_control_create": {"module": "invoice", "module_label": "INVOICE", "label": "Proforma Control and Create List", "title": "Proforma Control and Create List", "description": "Proforma kontrol ve oluşturma işlemleri."},
    "bavel_invoice_list": {"module": "invoice", "module_label": "INVOICE", "label": "Bavel Invoice List", "title": "Bavel Invoice List", "description": "Bavel fatura listesi ve entegrasyon durumu."},
    "credit_control_list": {"module": "invoice", "module_label": "INVOICE", "label": "Credit Control List", "title": "Credit Control List", "description": "Kredi ve tahsilat kontrol listesi."},
    "quick_invoice": {"module": "invoice", "module_label": "INVOICE", "label": "Quick Invoice", "title": "Quick Invoice", "description": "Hızlı fatura işlemleri."},
    "quick_invoice_new": {"module": "invoice", "module_label": "INVOICE", "label": "Quick Invoice New", "title": "Quick Invoice New", "description": "Yeni hızlı fatura oluşturma."},
    "safe_receipt": {"module": "invoice", "module_label": "INVOICE", "label": "Safe Receipt", "title": "Safe Receipt", "description": "Kasa makbuzu işlemleri."},
    "e_invoice_definitions": {"module": "invoice", "module_label": "INVOICE", "label": "E-Invoice Definitions", "title": "E-Invoice Definitions", "description": "E-fatura tanım ve entegrasyon ayarları."},
}


@login_required
def planned_screen(request, screen_key):
    screen = PLANNED_SCREENS.get(screen_key)
    if not screen:
        return HttpResponse("Ekran bulunamadı.", status=404)
    properties, selected = _selected_property(request)
    planned_nav = [] if screen_key == "licence_info" else [
        {"label": item["label"], "url": reverse(f"operations:{key}")}
        for key, item in PLANNED_SCREENS.items()
        if item["module"] == screen["module"]
    ]
    rows = []
    if selected:
        if screen_key in {"front_office_status", "group_reservations", "tour_operator_integrations", "folio_balances", "reservation_updates"}:
            for item in selected.reservations.select_related("guest", "channel").order_by("-created_at")[:100]:
                rows.append({"label": item.reference, "meta": f"{item.guest} · {item.check_in} – {item.check_out}", "status": item.get_status_display()})
        elif screen_key in {"room_type_availability", "available_rooms"}:
            for item in selected.unit_types.prefetch_related("units")[:100]:
                rows.append({"label": item.name, "meta": f"{item.code} · kapasite {item.capacity_per_unit}", "status": f"{item.units.filter(is_active=True).count()} aktif ünite"})
        elif screen_key == "closed_room_list":
            for item in selected.units.select_related("unit_type").filter(is_active=True).exclude(status="available")[:100]:
                rows.append({"label": item.code, "meta": item.unit_type.name, "status": item.get_status_display()})
        elif screen_key == "credit_accounts":
            for item in selected.credit_accounts.all()[:100]:
                rows.append({"label": item.name, "meta": f"{item.code} · limit {item.credit_limit} {item.currency}", "status": f"Bakiye {item.balance} {item.currency}"})
        elif screen_key == "guest_cards":
            for item in Guest.objects.filter(property=selected).order_by("last_name", "first_name")[:100]:
                rows.append({"label": f"{item.first_name} {item.last_name}", "meta": item.email or item.phone or "İletişim bilgisi yok", "status": "Misafir profili"})
        elif screen_key == "lost_and_found":
            for item in selected.lost_and_found_items.all()[:100]:
                rows.append({"label": item.description, "meta": f"{item.found_location or '-'} · {item.found_at}", "status": item.get_status_display()})
        elif screen_key == "hotel_phone_book":
            for item in selected.phone_book_entries.filter(is_active=True)[:100]:
                rows.append({"label": item.name, "meta": f"{item.department or '-'} · {item.email or '-'}", "status": item.phone})
        elif screen_key == "park_entry":
            for item in selected.park_entries.order_by("-entry_at")[:100]:
                rows.append({"label": item.plate_number, "meta": f"{item.parking_space or '-'} · {item.entry_at}", "status": "Çıkış yapıldı" if item.exit_at else "İçeride"})
        elif screen_key in {"archived_end_of_day_reports", "night_audit_html_reports", "end_of_year", "end_of_day_log_2"}:
            for item in selected.night_audit_runs.select_related("actor")[:100]:
                rows.append({"label": str(item.audit_date), "meta": f"{item.actor or '-'} · {item.completed_at or '-'}", "status": item.get_status_display()})
        elif screen_key in {"all_invoices", "mustahsil", "all_accounts", "sales_price_agreements", "invoice_bulk_control", "proforma_invoice_list", "proforma_control_create", "bavel_invoice_list", "credit_control_list", "quick_invoice", "quick_invoice_new", "safe_receipt", "e_invoice_definitions"}:
            for item in selected.invoices.order_by("-issue_date", "-id")[:100]:
                rows.append({"label": item.number, "meta": f"{item.customer_name} · {item.issue_date}", "status": f"{item.total} {item.currency} · {item.get_status_display()}", "url": reverse("operations:invoice_detail", args=[item.id]) + f"?property_id={selected.id}"})
    actions = []
    if screen_key in {"guest_cards"}:
        actions.append({"label": "CRM misafir profilleri", "url": reverse("operations:crm_guests") + f"?property_id={selected.id}"})
    if screen_key in {"all_invoices", "quick_invoice", "quick_invoice_new"}:
        actions.append({"label": "Yeni fatura", "url": reverse("operations:invoices") + f"?property_id={selected.id}"})
    if screen_key in {"archived_end_of_day_reports", "night_audit_html_reports", "end_of_day_log_2"}:
        actions.append({"label": "Night Audit çalıştır", "url": reverse("operations:night_audit") + f"?property_id={selected.id}"})
    return render(request, "booking/operations/planned_screen.html", {
        "title": screen["title"],
        "properties": properties,
        "selected_property": selected,
        "planned_screen": screen,
        "planned_nav": planned_nav,
        "screen_rows": rows,
        "screen_actions": actions,
        "license_version": __version__,
        "license_modules": ["Setup", "Front Office", "CRM", "Channel Management", "Operations", "Invoice / Accounting"],
    })


@login_required
def front_office(request):
    properties, selected = _selected_property(request)
    if _permission_denied(request, selected, "operations.front_office.manage"):
        return HttpResponseForbidden("Bu tesis için Front Office yetkiniz yok.")
    tab = request.GET.get("tab", "all")
    today = timezone.localdate()
    reservations = Reservation.objects.filter(property=selected).select_related("guest", "channel").prefetch_related("items") if selected else Reservation.objects.none()
    if tab == "expected_arrivals":
        reservations = reservations.filter(status__in=[ReservationStatus.PENDING, ReservationStatus.CONFIRMED], check_in__gte=today)
    elif tab == "in_house":
        reservations = reservations.filter(items__stay_status=StayStatus.CHECKED_IN).distinct()
    elif tab == "expected_departures":
        reservations = reservations.filter(items__stay_status=StayStatus.CHECKED_IN, check_out__gte=today).distinct()
    elif tab == "departures":
        reservations = reservations.filter(items__stay_status__in=[StayStatus.CHECKED_OUT, StayStatus.EARLY_CHECKOUT]).distinct()
    elif tab == "no_show":
        reservations = reservations.filter(status=ReservationStatus.NO_SHOW)
    elif tab == "cancelled":
        reservations = reservations.filter(status=ReservationStatus.CANCELLED)
    return render(request, "booking/operations/front_office.html", {"title": "Front Office", "properties": properties, "selected_property": selected, "reservations": reservations[:250], "tab": tab, "today": today, "tabs": [("all", "Tümü"), ("expected_arrivals", "Beklenen gelişler"), ("in_house", "In-house"), ("expected_departures", "Beklenen çıkışlar"), ("departures", "Ayrılanlar"), ("no_show", "No-show"), ("cancelled", "İptaller")]})


@login_required
def accounting_definitions(request):
    properties, selected = _selected_property(request)
    if _permission_denied(request, selected, "operations.hotel.dictionaries.manage"):
        return HttpResponseForbidden("Bu tesis için muhasebe tanımları yetkiniz yok.")
    department_form = DepartmentDefinitionForm(request.POST or None, prefix="department")
    revenue_form = RevenueCodeForm(request.POST or None, prefix="revenue")
    if request.method == "POST" and selected:
        action = request.POST.get("action")
        if action == "department" and department_form.is_valid():
            obj = department_form.save(commit=False); obj.property = selected; obj.save(); messages.success(request, "Departman tanımı kaydedildi.")
        elif action == "revenue" and revenue_form.is_valid():
            obj = revenue_form.save(commit=False); obj.property = selected; obj.save(); messages.success(request, "Gelir kodu kaydedildi.")
        return redirect(f"{reverse('operations:accounting_definitions')}?property_id={selected.id}")
    return render(request, "booking/operations/accounting_definitions.html", {"title": "Muhasebe Tanımları", "properties": properties, "selected_property": selected, "department_form": department_form, "revenue_form": revenue_form, "departments": selected.department_definitions.all() if selected else DepartmentDefinition.objects.none(), "revenue_codes": selected.revenue_codes.all() if selected else RevenueCode.objects.none()})


def _finance_context(request):
    properties, selected = _selected_property(request)
    if _permission_denied(request, selected, "operations.financial.manage"):
        return properties, selected, HttpResponseForbidden("Bu tesis için finans yetkiniz yok.")
    return properties, selected, None


@login_required
def daily_currency_rates(request):
    properties, selected, denied = _finance_context(request)
    if denied:
        return denied
    currency_form = CurrencyDefinitionForm(request.POST or None, prefix="currency")
    rate_form = DailyCurrencyRateForm(request.POST or None, prefix="rate")
    if request.method == "POST" and selected:
        action = request.POST.get("action")
        form = currency_form if action == "currency" else rate_form
        if form.is_valid():
            obj = form.save(commit=False)
            obj.property = selected
            obj.save()
            messages.success(request, "Döviz tanımı kaydedildi." if action == "currency" else "Günlük kur kaydedildi.")
            return redirect(f"{reverse('operations:daily_currency_rates')}?property_id={selected.id}")
    currencies = selected.currency_definitions.all() if selected else CurrencyDefinition.objects.none()
    rates = selected.daily_currency_rates.all()[:100] if selected else DailyCurrencyRate.objects.none()
    return render(request, "booking/operations/daily_currency_rates.html", {
        "title": "Döviz Kurları", "properties": properties, "selected_property": selected,
        "currency_form": currency_form, "rate_form": rate_form, "currencies": currencies, "rates": rates,
    })


def _apply_rental_quote(booking):
    if not booking.rental_rate_id or not booking.pickup_at or not booking.dropoff_at:
        return None
    extra_ids = booking.extra_products if isinstance(booking.extra_products, list) else []
    insurance_id = int(booking.insurance_package) if str(booking.insurance_package).isdigit() else None
    quote = calculate_rental_quote(
        rate=booking.rental_rate,
        pickup_at=booking.pickup_at,
        dropoff_at=booking.dropoff_at,
        extra_product_ids=extra_ids,
        insurance_package_id=insurance_id,
        pickup_location=booking.pickup_location_ref,
        dropoff_location=booking.dropoff_location_ref,
        promo_code=booking.promo_code,
        corporate_code=booking.corporate_code,
        loyalty_code=booking.loyalty_code,
        channel_code=booking.channel_reference,
        vehicle_class=booking.vehicle_class,
    )
    booking.daily_rate = booking.rental_rate.daily_rate
    booking.total_amount = quote.total_amount
    booking.deposit_amount = quote.deposit_amount
    booking.currency = quote.currency
    return quote


def _rental_search_values(request):
    pickup = parse_datetime(request.POST.get("pickup_at") or request.GET.get("pickup_at") or "")
    dropoff = parse_datetime(request.POST.get("dropoff_at") or request.GET.get("dropoff_at") or "")
    if pickup and timezone.is_naive(pickup):
        pickup = timezone.make_aware(pickup)
    if dropoff and timezone.is_naive(dropoff):
        dropoff = timezone.make_aware(dropoff)
    return pickup, dropoff, request.POST.get("vehicle_class") or request.GET.get("vehicle_class") or ""


def _parking_search_values(request):
    start = parse_datetime(request.POST.get("start_at") or request.GET.get("start_at") or "")
    end = parse_datetime(request.POST.get("end_at") or request.GET.get("end_at") or "")
    if start and timezone.is_naive(start):
        start = timezone.make_aware(start)
    if end and timezone.is_naive(end):
        end = timezone.make_aware(end)
    return start, end


def _scope_rental_operation_form(form, selected):
    """Keep every FK choice inside the selected property boundary."""
    if not selected:
        return form
    if "property" in form.fields:
        form.fields.pop("property")
    queryset_map = {
        "vehicle": Vehicle.objects.filter(property=selected),
        "connection": RentalChannelConnection.objects.filter(property=selected, is_active=True),
        "device": ParkingDevice.objects.filter(property=selected, is_active=True),
        "telemetry": VehicleTelemetryEvent.objects.filter(property=selected).select_related("vehicle")[:100],
        "flight": RentalFlightStatus.objects.filter(booking__property=selected).select_related("booking")[:100],
        "booking": VehicleRentalBooking.objects.filter(property=selected),
        "rental_rate": VehicleRentalRate.objects.filter(vehicle__property=selected),
        "pickup_location_ref": RentalLocation.objects.filter(property=selected, is_active=True),
        "dropoff_location_ref": RentalLocation.objects.filter(property=selected, is_active=True),
        "parking_lot": ParkingLot.objects.filter(property=selected),
        "parking_space": ParkingSpace.objects.filter(parking_lot__property=selected),
        "reservation": ParkingReservation.objects.filter(property=selected),
        "handover": RentalHandover.objects.filter(booking__property=selected),
        "invoice": Invoice.objects.filter(property=selected),
        "gateway": PaymentGateway.objects.filter(property=selected),
        "guest": Guest.objects.filter(property=selected),
    }
    for name, queryset in queryset_map.items():
        if name in form.fields:
            form.fields[name].queryset = queryset
    return form


@login_required
def rental_operations(request):
    """Dynamic operational back office for rental and parking workflows."""
    properties, selected = _selected_property(request)
    if _permission_denied(request, selected, "operations.front_office.manage"):
        return HttpResponseForbidden("Bu tesis için araç kiralama ve otopark operasyon yetkiniz yok.")

    entity = request.POST.get("entity") or request.GET.get("entity") or "locations"
    module = "parking" if entity in {"parking_bookings", "parking_map", "parking_devices", "parking_subscriptions", "parking_access", "valet", "parking_penalties"} else "vehicle_rental"
    if _module_license_denied(request, selected, module):
        return HttpResponseForbidden("Bu tesis için ilgili modül lisansı aktif değil.")
    form_classes = {
        "rental_bookings": VehicleRentalBookingForm,
        "parking_bookings": ParkingReservationForm,
        "channel_connections": RentalChannelConnectionForm,
        "channel_mappings": RentalChannelMappingForm,
        "pricing_rules": RentalPricingRuleForm,
        "telemetry": VehicleTelemetryEventForm,
        "flight": RentalFlightStatusForm,
        "parking_devices": ParkingDeviceForm,
        "locations": RentalLocationForm,
        "extras": RentalExtraProductForm,
        "insurance": RentalInsurancePackageForm,
        "handovers": RentalHandoverForm,
        "handover_photos": RentalHandoverPhotoForm,
        "damage": RentalDamageCaseForm,
        "maintenance": VehicleMaintenanceRecordForm,
        "fines": RentalFineForm,
        "parking_subscriptions": ParkingSubscriptionForm,
        "parking_access": ParkingAccessEventForm,
        "valet": ParkingValetRecordForm,
        "parking_penalties": ParkingPenaltyForm,
        "contracts": RentalContractForm,
        "payments": RentalPaymentForm,
        "invoices": RentalInvoiceForm,
        "driver_profiles": RentalDriverProfileForm,
        "cancellation_policies": RentalCancellationPolicyForm,
        "tax_rules": RentalTaxRuleForm,
    }
    edit_id = request.GET.get("edit_id") or request.POST.get("edit_id")
    instance = None
    if selected and edit_id and entity == "rental_bookings":
        instance = VehicleRentalBooking.objects.filter(property=selected, pk=edit_id).first()
    elif selected and edit_id and entity == "parking_bookings":
        instance = ParkingReservation.objects.filter(property=selected, pk=edit_id).first()
    form_class = form_classes.get(entity, RentalLocationForm)
    form_kwargs = {"instance": instance}
    if entity in {"rental_bookings", "parking_bookings"}:
        form_kwargs["property_"] = selected
    form = form_class(request.POST or None, request.FILES or None, **form_kwargs)
    _scope_rental_operation_form(form, selected)
    if request.method == "POST" and selected and entity == "privacy_requests":
        request_id = request.POST.get("request_id")
        status = request.POST.get("status")
        data_request = RentalDataRequest.objects.select_related("booking", "driver_profile").filter(
            property=selected, pk=request_id,
        ).first()
        if data_request and status in {RentalDataRequest.Status.COMPLETED, RentalDataRequest.Status.REJECTED}:
            with transaction.atomic():
                if status == RentalDataRequest.Status.COMPLETED and data_request.request_type == RentalDataRequest.RequestType.DELETION:
                    booking = data_request.booking
                    if booking:
                        booking.customer_name = "Anonim müşteri"
                        booking.customer_email = ""
                        booking.customer_phone = ""
                        booking.license_number = ""
                        booking.driver_license_country = ""
                        booking.privacy_consent_at = None
                        booking.save(update_fields=["customer_name", "customer_email", "customer_phone", "license_number", "driver_license_country", "privacy_consent_at", "updated_at"])
                        RentalAuditEvent.objects.create(property=selected, booking=booking, actor=request.user, action="privacy_data_deleted", source="backoffice")
                    driver = data_request.driver_profile
                    if driver:
                        if driver.license_document:
                            default_storage.delete(driver.license_document.name)
                        driver.full_name = "Anonim müşteri"
                        driver.email = ""
                        driver.phone = ""
                        driver.license_number = ""
                        driver.identity_document_ref = ""
                        driver.license_document = ""
                        driver.notes = ""
                        driver.save(update_fields=["full_name", "email", "phone", "license_number", "identity_document_ref", "license_document", "notes", "updated_at"])
                data_request.status = status
                data_request.completed_at = timezone.now()
                data_request.save(update_fields=["status", "completed_at"])
                RentalPrivacyEvent.objects.create(
                    property=selected, booking=data_request.booking, driver_profile=data_request.driver_profile,
                    event_type=RentalPrivacyEvent.EventType.DELETION_REQUEST if data_request.request_type == RentalDataRequest.RequestType.DELETION else RentalPrivacyEvent.EventType.DATA_EXPORT,
                    policy_version=data_request.booking.privacy_policy_version if data_request.booking else "",
                    requester_email=data_request.requester_email, source="backoffice", metadata={"status": status},
                )
            messages.success(request, "KVKK talebi sonuçlandırıldı.")
        else:
            messages.error(request, "KVKK talebi bulunamadı veya durum geçersiz.")
        return redirect(f"{reverse('operations:rental_operations')}?property_id={selected.id}&entity=privacy_requests")
    if request.method == "POST" and selected and request.POST.get("action") in {"capture_payment", "refund_payment", "manual_refund_payment"}:
        payment = RentalPayment.objects.select_related("booking", "gateway").filter(
            pk=request.POST.get("payment_id"), booking__property=selected,
        ).first()
        if not payment:
            messages.error(request, "Ödeme kaydı bulunamadı.")
        else:
            try:
                if request.POST["action"] == "capture_payment":
                    capture_rental_payment(payment=payment, actor=request.user)
                    messages.success(request, "Ödeme sağlayıcı üzerinden yakalandı.")
                elif request.POST["action"] == "manual_refund_payment":
                    record_manual_bank_refund(
                        payment=payment, actor=request.user,
                        refund_reference=request.POST.get("refund_reference", ""),
                        note=request.POST.get("refund_note", ""),
                    )
                    messages.success(request, "Banka panelindeki iade ERP'ye islendi.")
                else:
                    refund_rental_payment(payment=payment, actor=request.user)
                    messages.success(request, "Ödeme sağlayıcı üzerinden iade edildi.")
            except (PaymentConfigurationError, PaymentProviderError) as exc:
                messages.error(request, str(exc))
        return redirect(f"{reverse('operations:rental_operations')}?property_id={selected.id}&entity=payments")
    if request.method == "POST" and selected and form.is_valid():
        obj = form.save(commit=False)
        if hasattr(obj, "property_id"):
            obj.property = selected
        if entity in {"rental_bookings", "parking_bookings"}:
            obj.created_by = request.user
        if entity == "rental_bookings":
            _apply_rental_quote(obj)
        elif entity == "parking_bookings" and obj.parking_lot_id:
            obj.amount = calculate_parking_quote(parking_lot=obj.parking_lot, start_at=obj.start_at, end_at=obj.end_at)
        if isinstance(obj, RentalHandover):
            obj.recorded_by = request.user
        if isinstance(obj, RentalDamageCase):
            obj.vehicle = obj.booking.vehicle
        if isinstance(obj, VehicleMaintenanceRecord):
            obj.property = selected
        if isinstance(obj, RentalAuditEvent):
            obj.property = selected
        if entity == "rental_bookings":
            save_rental_booking(obj)
        elif entity == "parking_bookings":
            save_parking_reservation(obj)
        else:
            obj.save()
        if entity == "handovers" and isinstance(obj, RentalHandover) and obj.kind == RentalHandover.Kind.RETURN:
            upsert_rental_settlement(booking=obj.booking, actor=request.user)
        if entity in {"rentals", "rental_bookings"}:
            queue_rental_notifications(obj)
            if obj.prepayment_amount:
                create_pending_rental_payment(booking=obj, amount=obj.prepayment_amount)
        messages.success(request, "Operasyon kaydı başarıyla kaydedildi.")
        return redirect(f"{reverse('operations:rental_operations')}?property_id={selected.id}&entity={entity}")

    parking_map = []
    if selected:
        now = timezone.now()
        active_statuses = [ParkingReservation.Status.PENDING, ParkingReservation.Status.CONFIRMED, ParkingReservation.Status.CHECKED_IN]
        for lot in selected.parking_lots.prefetch_related("spaces"):
            active_space_ids = set(ParkingReservation.objects.filter(
                parking_lot=lot, parking_space__isnull=False, status__in=active_statuses,
                start_at__lte=now, end_at__gt=now,
            ).values_list("parking_space_id", flat=True))
            spaces = list(lot.spaces.filter(is_active=True))
            for space in spaces:
                space.map_state = "occupied" if space.id in active_space_ids else space.status
                space.map_label = {"occupied": "Dolu", "available": "Müsait", "maintenance": "Bakım", "blocked": "Bloke"}.get(space.map_state, space.map_state)
            lot.map_spaces = spaces
            lot.map_total = lot.capacity or len(spaces)
            lot.map_occupied = len(active_space_ids)
            lot.map_available = max(lot.map_total - lot.map_occupied, 0)
            parking_map.append(lot)

    context = {
        "title": "Araç Kiralama ve Otopark Operasyonları",
        "properties": properties,
        "selected_property": selected,
        "entity": entity,
        "form": form,
        "locations": RentalLocation.objects.filter(property=selected)[:100] if selected else RentalLocation.objects.none(),
        "rental_bookings": VehicleRentalBooking.objects.filter(property=selected).select_related("vehicle", "rental_rate")[:100] if selected else VehicleRentalBooking.objects.none(),
        "parking_bookings": ParkingReservation.objects.filter(property=selected).select_related("parking_lot", "parking_space")[:100] if selected else ParkingReservation.objects.none(),
        "channel_connections": RentalChannelConnection.objects.filter(property=selected)[:100] if selected else RentalChannelConnection.objects.none(),
        "channel_mappings": RentalChannelMapping.objects.filter(connection__property=selected).select_related("connection", "vehicle")[:100] if selected else RentalChannelMapping.objects.none(),
        "pricing_rules": RentalPricingRule.objects.filter(property=selected)[:100] if selected else RentalPricingRule.objects.none(),
        "telemetry": VehicleTelemetryEvent.objects.filter(property=selected).select_related("vehicle")[:100] if selected else VehicleTelemetryEvent.objects.none(),
        "flight_statuses": RentalFlightStatus.objects.filter(booking__property=selected).select_related("booking")[:100] if selected else RentalFlightStatus.objects.none(),
        "parking_devices": ParkingDevice.objects.filter(property=selected).select_related("parking_lot")[:100] if selected else ParkingDevice.objects.none(),
        "extras": RentalExtraProduct.objects.filter(property=selected)[:100] if selected else RentalExtraProduct.objects.none(),
        "insurance_packages": RentalInsurancePackage.objects.filter(property=selected)[:100] if selected else RentalInsurancePackage.objects.none(),
        "handovers": RentalHandover.objects.filter(booking__property=selected).select_related("booking", "recorded_by")[:100] if selected else RentalHandover.objects.none(),
        "damage_cases": RentalDamageCase.objects.filter(booking__property=selected).select_related("booking", "vehicle")[:100] if selected else RentalDamageCase.objects.none(),
        "maintenance_records": VehicleMaintenanceRecord.objects.filter(property=selected).select_related("vehicle")[:100] if selected else VehicleMaintenanceRecord.objects.none(),
        "fines": RentalFine.objects.filter(booking__property=selected).select_related("booking", "vehicle")[:100] if selected else RentalFine.objects.none(),
        "parking_subscriptions": ParkingSubscription.objects.filter(property=selected).select_related("parking_lot")[:100] if selected else ParkingSubscription.objects.none(),
        "access_events": ParkingAccessEvent.objects.filter(property=selected).select_related("parking_lot", "parking_space")[:100] if selected else ParkingAccessEvent.objects.none(),
        "valet_records": ParkingValetRecord.objects.filter(parking_lot__property=selected).select_related("parking_lot", "reservation")[:100] if selected else ParkingValetRecord.objects.none(),
        "parking_penalties": ParkingPenalty.objects.filter(parking_lot__property=selected).select_related("parking_lot")[:100] if selected else ParkingPenalty.objects.none(),
        "contracts": RentalContract.objects.filter(booking__property=selected).select_related("booking")[:100] if selected else RentalContract.objects.none(),
        "payments": RentalPayment.objects.filter(booking__property=selected).select_related("booking", "gateway")[:100] if selected else RentalPayment.objects.none(),
        "rental_invoices": RentalInvoice.objects.filter(booking__property=selected).select_related("booking", "invoice")[:100] if selected else RentalInvoice.objects.none(),
        "sync_events": RentalChannelSyncEvent.objects.filter(property=selected)[:100] if selected else RentalChannelSyncEvent.objects.none(),
        "notifications": RentalNotification.objects.filter(booking__property=selected)[:100] if selected else RentalNotification.objects.none(),
        "driver_profiles": RentalDriverProfile.objects.filter(property=selected).select_related("guest")[:100] if selected else RentalDriverProfile.objects.none(),
        "cancellation_policies": RentalCancellationPolicy.objects.filter(property=selected)[:100] if selected else RentalCancellationPolicy.objects.none(),
        "tax_rules": RentalTaxRule.objects.filter(property=selected)[:100] if selected else RentalTaxRule.objects.none(),
        "privacy_requests": RentalDataRequest.objects.filter(property=selected).select_related("booking", "driver_profile")[:100] if selected else RentalDataRequest.objects.none(),
        "parking_map": parking_map,
    }
    return render(request, "booking/operations/rental_operations.html", context)


@login_required
def rental_booking_detail(request, booking_id):
    """Property-scoped rental detail and status control screen."""
    properties, selected = _selected_property(request)
    if _permission_denied(request, selected, "operations.front_office.manage"):
        return HttpResponseForbidden("Bu tesis için kiralama detayına erişim yetkiniz yok.")
    if _module_license_denied(request, selected, "vehicle_rental"):
        return HttpResponseForbidden("Bu tesis için Araç Kiralama modül lisansı aktif değil.")
    booking = VehicleRentalBooking.objects.select_related(
        "vehicle", "rental_rate", "driver_profile", "cancellation_policy_ref",
    ).prefetch_related("handovers", "damage_cases", "payments", "rental_invoices").filter(
        property=selected, pk=booking_id,
    ).first()
    if not booking:
        return HttpResponse("Kiralama kaydı bulunamadı.", status=404)
    edit_form = VehicleRentalBookingForm(request.POST or None, instance=booking, property_=selected)
    if request.method == "POST" and request.POST.get("action") == "save":
        if edit_form.is_valid():
            updated = edit_form.save(commit=False)
            updated.property = selected
            _apply_rental_quote(updated)
            save_rental_booking(updated)
            queue_first_party_reservation_event(booking=updated, entity="rentals", event_type="reservation_updated")
            RentalAuditEvent.objects.create(property=selected, booking=updated, actor=request.user, action="booking_updated", source=updated.source)
            messages.success(request, "Kiralama kaydı güncellendi.")
            return redirect(request.path + f"?property_id={selected.id}")
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "invoice_settlement":
            settlement = getattr(booking, "settlement", None)
            if not settlement:
                settlement = upsert_rental_settlement(booking=booking, actor=request.user)
            try:
                invoice = issue_settlement_invoice(settlement=settlement, actor=request.user)
            except ValueError as exc:
                messages.error(request, str(exc))
            else:
                messages.success(request, f"Settlement faturası oluşturuldu: {invoice.number}")
            return redirect(request.path + f"?property_id={selected.id}")
        status_map = {
            "confirmed": VehicleRentalBooking.Status.CONFIRMED,
            "active": VehicleRentalBooking.Status.ACTIVE,
            "completed": VehicleRentalBooking.Status.COMPLETED,
            "cancelled": VehicleRentalBooking.Status.CANCELLED,
            "no_show": VehicleRentalBooking.Status.NO_SHOW,
        }
        if action in status_map:
            booking.status = status_map[action]
            if action == "cancelled":
                booking.cancelled_at = timezone.now()
            if action == "no_show":
                booking.no_show_at = timezone.now()
            booking.save(update_fields=["status", "cancelled_at", "no_show_at", "updated_at"])
            queue_first_party_reservation_event(booking=booking, entity="rentals", event_type="reservation_status_changed")
            RentalAuditEvent.objects.create(property=selected, booking=booking, actor=request.user, action=f"detail_status_{booking.status}", source=booking.source)
            messages.success(request, "Kiralama durumu güncellendi.")
            return redirect(request.path + f"?property_id={selected.id}")
    return render(request, "booking/operations/rental_booking_detail.html", {
        "title": f"Kiralama {booking.confirmation_code}",
        "properties": properties,
        "selected_property": selected,
        "booking": booking,
        "edit_form": edit_form,
        "audit_events": booking.audit_events.select_related("actor")[:100],
    })


@login_required
def fleet_reports(request):
    properties, selected = _selected_property(request)
    if _permission_denied(request, selected, "operations.front_office.manage"):
        return HttpResponseForbidden("Bu tesis iÃ§in filo raporlarÄ± eriÅŸiminiz yok.")
    if not selected:
        return render(request, "booking/operations/fleet_reports.html", {"title": "Filo ve Otopark RaporlarÄ±", "properties": properties, "selected_property": selected})
    today = timezone.localdate()
    vehicles = selected.vehicles.filter(is_active=True)
    rental_bookings = selected.vehicle_rental_bookings.all()
    parking_bookings = selected.parking_reservations.all()
    active_rentals = rental_bookings.filter(status__in=[VehicleRentalBooking.Status.CONFIRMED, VehicleRentalBooking.Status.ACTIVE])
    active_parking = parking_bookings.filter(status__in=[ParkingReservation.Status.CONFIRMED, ParkingReservation.Status.CHECKED_IN])
    revenue = rental_bookings.filter(status__in=[VehicleRentalBooking.Status.CONFIRMED, VehicleRentalBooking.Status.ACTIVE, VehicleRentalBooking.Status.COMPLETED]).aggregate(total=Sum("total_amount"))["total"] or 0
    parking_revenue = parking_bookings.filter(status__in=[ParkingReservation.Status.CONFIRMED, ParkingReservation.Status.CHECKED_IN, ParkingReservation.Status.CHECKED_OUT]).aggregate(total=Sum("amount"))["total"] or 0
    return render(request, "booking/operations/fleet_reports.html", {
        "title": "Filo ve Otopark Raporları", "properties": properties, "selected_property": selected,
        "today": today, "vehicle_count": vehicles.count(), "active_rentals": active_rentals.count(),
        "available_vehicles": vehicles.filter(status="available").count(), "rental_revenue": revenue,
        "parking_count": selected.parking_lots.filter(is_active=True).count(), "active_parking": active_parking.count(),
        "parking_revenue": parking_revenue, "maintenance_due": VehicleMaintenanceRecord.objects.filter(property=selected, status__in=["planned", "overdue"]).count(),
        "telemetry_events": VehicleTelemetryEvent.objects.filter(property=selected, occurred_at__date=today).count(),
    })


@login_required
def vehicle_fleet(request, entity="vehicles", setup_only=False, screen="combined"):
    properties, selected = _selected_property(request)
    if _permission_denied(request, selected, "operations.front_office.manage"):
        return HttpResponseForbidden("Bu tesis için araç filosu yetkiniz yok.")
    module = "parking" if entity in {"parking", "parking_reservations", "spaces"} else "vehicle_rental"
    if _module_license_denied(request, selected, module):
        return HttpResponseForbidden("Bu tesis için ilgili modül lisansı aktif değil.")

    active_entity = request.POST.get("entity") or entity
    form = VehicleForm(request.POST or None)
    parking_lot_form = ParkingLotForm(request.POST or None)
    parking_space_form = ParkingSpaceForm(request.POST or None, property_=selected)
    vehicle_photo_form = VehiclePhotoForm(request.POST or None, request.FILES or None, property_=selected)
    rental_rate_form = VehicleRentalRateForm(request.POST or None, property_=selected)
    parking_reservation_form = ParkingReservationForm(request.POST or None, property_=selected)
    rental_booking_form = VehicleRentalBookingForm(request.POST or None, property_=selected)
    forms_by_entity = {
        "vehicles": form, "parking": parking_lot_form, "spaces": parking_space_form,
        "vehicle_photos": vehicle_photo_form,
        "rental_rates": rental_rate_form, "parking_reservations": parking_reservation_form,
        "rentals": rental_booking_form,
    }
    if request.method == "POST" and selected and request.POST.get("action") in {"confirm", "confirmed", "active", "completed", "cancelled", "no_show"}:
        action = request.POST["action"]
        booking_id = request.POST.get("booking_id")
        if active_entity == "rentals":
            booking = selected.vehicle_rental_bookings.filter(pk=booking_id).first()
            if booking:
                rental_status = {
                    "confirm": VehicleRentalBooking.Status.CONFIRMED,
                    "confirmed": VehicleRentalBooking.Status.CONFIRMED,
                    "active": VehicleRentalBooking.Status.ACTIVE,
                    "completed": VehicleRentalBooking.Status.COMPLETED,
                    "cancelled": VehicleRentalBooking.Status.CANCELLED,
                    "no_show": VehicleRentalBooking.Status.NO_SHOW,
                }.get(action, VehicleRentalBooking.Status.PENDING)
                booking.status = rental_status
                if action == "cancelled":
                    booking.cancelled_at = timezone.now()
                if action == "no_show":
                    booking.no_show_at = timezone.now()
                booking.save(update_fields=["status", "cancelled_at", "no_show_at", "updated_at"])
                RentalAuditEvent.objects.create(property=selected, booking=booking, actor=request.user, action=f"status_{rental_status}", source=booking.source)
                messages.success(request, "Kiralama rezervasyon durumu güncellendi.")
                return redirect(f"{reverse('operations:vehicle_rental_bookings')}?property_id={selected.id}")
        if active_entity == "parking_reservations":
            booking = selected.parking_reservations.filter(pk=booking_id).first()
            if booking:
                parking_status = {
                    "confirm": ParkingReservation.Status.CONFIRMED,
                    "confirmed": ParkingReservation.Status.CONFIRMED,
                    "active": ParkingReservation.Status.CHECKED_IN,
                    "completed": ParkingReservation.Status.CHECKED_OUT,
                    "cancelled": ParkingReservation.Status.CANCELLED,
                    "no_show": ParkingReservation.Status.NO_SHOW,
                }.get(action, ParkingReservation.Status.PENDING)
                booking.status = parking_status
                booking.save(update_fields=["status", "updated_at"])
                queue_first_party_reservation_event(booking=booking, entity="parking", event_type="reservation_status_changed")
                RentalAuditEvent.objects.create(
                    property=selected, actor=request.user, action=f"parking_status_{parking_status}",
                    source=booking.source, payload={"parking_reservation_id": booking.id, "confirmation_code": booking.confirmation_code},
                )
                messages.success(request, "Otopark rezervasyon durumu güncellendi.")
                return redirect(f"{reverse('operations:parking_reservations')}?property_id={selected.id}")
    if request.method == "POST" and selected:
        active_form = forms_by_entity.get(active_entity, form)
        if active_form.is_valid():
            obj = active_form.save(commit=False)
            if active_entity == "vehicle_photos":
                obj = vehicle_photo_form.save()
            elif active_entity in {"vehicles", "parking", "parking_reservations", "rentals"}:
                obj.property = selected
                if active_entity == "rentals":
                    _apply_rental_quote(obj)
                elif active_entity == "parking_reservations" and obj.parking_lot_id:
                    obj.amount = calculate_parking_quote(parking_lot=obj.parking_lot, start_at=obj.start_at, end_at=obj.end_at)
            if active_entity in {"parking_reservations", "rentals"}:
                obj.created_by = request.user
            if active_entity == "rentals":
                save_rental_booking(obj)
            elif active_entity == "parking_reservations":
                save_parking_reservation(obj)
                queue_first_party_reservation_event(booking=obj, entity="parking", event_type="reservation_updated")
            else:
                obj.save()
            if active_entity == "rentals":
                queue_rental_notifications(obj)
                if obj.prepayment_amount:
                    create_pending_rental_payment(booking=obj, amount=obj.prepayment_amount)
            messages.success(request, "Kayıt başarıyla kaydedildi.")
            if screen == "vehicle_setup":
                target = "vehicle_definitions"
            elif screen == "parking_setup":
                target = "parking_definitions"
            elif screen == "parking_business":
                target = "parking_management"
            elif screen == "rental_business":
                target = "vehicle_rentals_management"
            else:
                target = "vehicle_fleet" if active_entity in {"vehicles", "vehicle_photos"} else (
                    "parking_reservations" if active_entity in {"parking", "spaces", "parking_reservations"} else "vehicle_rental_bookings"
                )
            return redirect(f"{reverse(f'operations:{target}')}?property_id={selected.id}")

    vehicles = selected.vehicles.all() if selected else Vehicle.objects.none()
    vehicle_photos = VehiclePhoto.objects.filter(vehicle__property=selected).select_related("vehicle") if selected else VehiclePhoto.objects.none()
    parking_lots = selected.parking_lots.prefetch_related("spaces") if selected else ParkingLot.objects.none()
    parking_spaces = ParkingSpace.objects.filter(parking_lot__property=selected).select_related("parking_lot") if selected else ParkingSpace.objects.none()
    rental_rates = VehicleRentalRate.objects.filter(vehicle__property=selected).select_related("vehicle") if selected else VehicleRentalRate.objects.none()
    parking_reservations = selected.parking_reservations.select_related("parking_lot", "parking_space")[:100] if selected else ParkingReservation.objects.none()
    rental_bookings = selected.vehicle_rental_bookings.select_related("vehicle", "rental_rate")[:100] if selected else VehicleRentalBooking.objects.none()
    fleet_widget_rental_url = request.build_absolute_uri(
        reverse("operations:fleet_widget", kwargs={"widget_key": selected.fleet_widget_key})
    ) + "?entity=rentals" if selected else ""
    fleet_widget_parking_url = request.build_absolute_uri(
        reverse("operations:fleet_widget", kwargs={"widget_key": selected.fleet_widget_key})
    ) + "?entity=parking" if selected else ""
    fleet_widget_rental_embed = f'<iframe src="{fleet_widget_rental_url}" width="100%" height="720" loading="lazy" title="Araç kiralama"></iframe>' if selected else ""
    fleet_widget_parking_embed = f'<iframe src="{fleet_widget_parking_url}" width="100%" height="720" loading="lazy" title="Otopark rezervasyonu"></iframe>' if selected else ""
    template_name = {
        "vehicle_setup": "booking/operations/vehicle_setup.html",
        "parking_setup": "booking/operations/parking_setup.html",
        "rental_business": "booking/operations/rental_business.html",
        "parking_business": "booking/operations/parking_business.html",
    }.get(screen, "booking/operations/vehicle_fleet.html")
    screen_titles = {
        "vehicle_setup": "Araç Tanımları",
        "parking_setup": "Parking Tanımları",
        "rental_business": "Araç Kiralama / Business",
        "parking_business": "Parking / Business",
    }
    return render(request, template_name, {
        "title": "Araç Filosu ve Otopark", "properties": properties, "selected_property": selected,
        "entity": active_entity, "setup_only": setup_only, "screen": screen,
        "screen_title": screen_titles.get(screen, "Araç Filosu ve Otopark"), "form": forms_by_entity.get(active_entity, form),
        "vehicle_form": form, "parking_lot_form": parking_lot_form, "parking_space_form": parking_space_form,
        "vehicle_photo_form": vehicle_photo_form, "vehicle_photos": vehicle_photos,
        "rental_rate_form": rental_rate_form, "parking_reservation_form": parking_reservation_form,
        "rental_booking_form": rental_booking_form, "vehicles": vehicles, "parking_lots": parking_lots,
        "parking_spaces": parking_spaces, "rental_rates": rental_rates,
        "parking_reservations": parking_reservations, "rental_bookings": rental_bookings,
        "fleet_widget_rental_url": fleet_widget_rental_url,
        "fleet_widget_parking_url": fleet_widget_parking_url,
        "fleet_widget_rental_embed": fleet_widget_rental_embed,
        "fleet_widget_parking_embed": fleet_widget_parking_embed,
    })


def vehicle_setup(request):
    return vehicle_fleet(request, entity="vehicles", setup_only=True, screen="vehicle_setup")


def parking_setup(request):
    return vehicle_fleet(request, entity="parking_reservations", setup_only=True, screen="parking_setup")


def vehicle_rental_business(request):
    return vehicle_fleet(request, entity="rentals", screen="rental_business")


def parking_business(request):
    return vehicle_fleet(request, entity="parking_reservations", screen="parking_business")


PUBLIC_PRIVACY_POLICY_VERSION = "2026-10"


def _apply_public_rental_consent(booking, form):
    """Persist only consent metadata; identity documents remain out of the public form."""
    booking.privacy_consent_at = timezone.now()
    booking.privacy_policy_version = PUBLIC_PRIVACY_POLICY_VERSION
    booking.marketing_consent = bool(form.cleaned_data.get("marketing_consent"))
    booking.data_retention_until = timezone.localdate() + timedelta(days=1825)
def _record_public_rental_consent(booking):
    RentalPrivacyEvent.objects.create(
        property=booking.property,
        booking=booking,
        event_type=RentalPrivacyEvent.EventType.CONSENT,
        policy_version=PUBLIC_PRIVACY_POLICY_VERSION,
        consent_given=True,
        requester_email=booking.customer_email,
        source="public",
    )


def online_fleet_booking(request):
    """Public, pending-only intake for parking and vehicle rental requests."""
    property_id = request.POST.get("property_id") or request.GET.get("property_id")
    selected = Property.objects.filter(id=property_id, is_active=True).first() if property_id else None
    entity = request.POST.get("entity") or request.GET.get("entity") or "parking"
    if selected and _module_license_denied(request, selected, "parking" if entity != "rentals" else "vehicle_rental"):
        return HttpResponseForbidden("Bu tesis için ilgili modül lisansı aktif değil.")
    parking_form = PublicParkingReservationForm(request.POST or None, property_=selected)
    rental_form = PublicRentalBookingForm(request.POST or None, property_=selected)
    if selected:
        start, end = _parking_search_values(request)
        parking_form.fields["parking_space"].queryset = available_parking_spaces(
            property_=selected, start_at=start, end_at=end,
        )
        pickup, dropoff, vehicle_class = _rental_search_values(request)
        rental_form.fields["vehicle"].queryset = available_rental_vehicles(
            property_=selected, pickup_at=pickup, dropoff_at=dropoff, vehicle_class=vehicle_class,
        )
        rental_form.fields["rental_rate"].queryset = VehicleRentalRate.objects.filter(vehicle__property=selected, vehicle__is_active=True, vehicle__online_enabled=True, is_active=True)
    active_form = rental_form if entity == "rentals" else parking_form
    if request.method == "POST" and selected and active_form.is_valid():
        obj = active_form.save(commit=False)
        obj.property = selected
        obj.source = ParkingReservation.Source.ONLINE
        obj.status = ParkingReservation.Status.PENDING
        if entity == "rentals":
            _apply_rental_quote(obj)
            _apply_public_rental_consent(obj, active_form)
        elif obj.parking_lot_id:
            obj.amount = calculate_parking_quote(parking_lot=obj.parking_lot, start_at=obj.start_at, end_at=obj.end_at)
        if entity == "rentals":
            save_rental_booking(obj)
            _record_public_rental_consent(obj)
            queue_property_first_party_event(
                property_=selected, event_type="reservation_created",
                payload={"entity": "rentals", "booking_id": obj.id, "confirmation_code": obj.confirmation_code,
                         "status": obj.status, "vehicle_id": obj.vehicle_id, "total_amount": str(obj.total_amount),
                         "currency": obj.currency, "source": obj.source},
            )
        else:
            save_parking_reservation(obj)
            queue_property_first_party_event(
                property_=selected, event_type="reservation_created",
                payload={"entity": "parking", "booking_id": obj.id, "confirmation_code": obj.confirmation_code,
                         "status": obj.status, "parking_lot_id": obj.parking_lot_id, "amount": str(obj.amount),
                         "currency": obj.currency, "source": obj.source},
            )
        if entity == "rentals":
            queue_rental_notifications(obj)
            if obj.prepayment_amount:
                create_pending_rental_payment(booking=obj, amount=obj.prepayment_amount)
        payment_url = reverse("operations:rental_payment_checkout", kwargs={"payment_token": obj.payment_token}) if entity == "rentals" and obj.prepayment_amount else ""
        return render(request, "booking/online/fleet_booking_public.html", {
            "selected_property": selected, "entity": entity, "submitted": True, "booking": obj, "payment_url": payment_url,
            "manage_url": request.build_absolute_uri(reverse("operations:rental_booking_self_service", kwargs={"token": obj.public_manage_token})),
        })
    return render(request, "booking/online/fleet_booking_public.html", {
        "selected_property": selected, "entity": entity, "parking_form": parking_form,
        "vehicles": rental_form.fields["vehicle"].queryset.prefetch_related("photos") if selected else Vehicle.objects.none(),
        "rental_form": rental_form, "form": active_form,
    })


def rental_booking_self_service(request, token):
    """Allow a renter to view/cancel a pending booking and request privacy actions."""
    booking = get_object_or_404(
        VehicleRentalBooking.objects.select_related("property", "vehicle", "rental_rate"),
        public_manage_token=token,
    )
    message = ""
    if request.method == "POST":
        requester_email = (request.POST.get("requester_email") or "").strip().lower()
        if booking.customer_email and requester_email != booking.customer_email.strip().lower():
            return HttpResponseForbidden("Rezervasyon e-postası doğrulanamadı.")
        action = request.POST.get("action")
        if action == "cancel" and booking.status in {VehicleRentalBooking.Status.PENDING, VehicleRentalBooking.Status.CONFIRMED}:
            booking.status = VehicleRentalBooking.Status.CANCELLED
            booking.cancelled_at = timezone.now()
            booking.save(update_fields=["status", "cancelled_at", "updated_at"])
            queue_first_party_reservation_event(booking=booking, entity="rentals", event_type="reservation_cancelled")
            message = "Rezervasyon iptal talebiniz kaydedildi."
        elif action in {"export", "deletion"}:
            request_type = RentalDataRequest.RequestType.EXPORT if action == "export" else RentalDataRequest.RequestType.DELETION
            data_request, created = RentalDataRequest.objects.get_or_create(
                property=booking.property,
                booking=booking,
                requester_email=requester_email or booking.customer_email,
                request_type=request_type,
                status=RentalDataRequest.Status.PENDING,
            )
            if created:
                RentalPrivacyEvent.objects.create(
                    property=booking.property,
                    booking=booking,
                    event_type=(RentalPrivacyEvent.EventType.DATA_EXPORT if action == "export" else RentalPrivacyEvent.EventType.DELETION_REQUEST),
                    policy_version=booking.privacy_policy_version,
                    requester_email=data_request.requester_email,
                    source="self_service",
                )
            message = "Talebiniz kaydedildi; tesis yöneticisi tarafından incelenecektir."
    return render(request, "booking/online/rental_booking_self_service.html", {
        "booking": booking,
        "message": message,
    })


def _fleet_widget_origin_matches(request, property_):
    configured = (property_.fleet_widget_domain or "").strip().lower().rstrip(".")
    if not configured:
        return not (request.META.get("HTTP_ORIGIN") or request.META.get("HTTP_REFERER"))
    configured = configured.removeprefix("https://").removeprefix("http://").split("/")[0]
    origin = request.META.get("HTTP_ORIGIN") or request.META.get("HTTP_REFERER")
    if not origin:
        return True
    hostname = (urlparse(origin).hostname or "").lower().rstrip(".")
    return hostname == configured or hostname.endswith(f".{configured}")


@csrf_exempt
@xframe_options_exempt
def fleet_widget(request, widget_key):
    """Public iframe intake for property-scoped parking and vehicle rentals."""
    selected = Property.objects.select_related("settings").filter(
        fleet_widget_key=widget_key, is_active=True
    ).first()
    if not selected or not _fleet_widget_origin_matches(request, selected):
        return render(request, "booking/widget_denied.html", {"channel": None}, status=403)

    entity = request.POST.get("entity") or request.GET.get("entity") or "parking"
    if entity not in {"parking", "rentals"}:
        entity = "parking"
    if _module_license_denied(request, selected, "parking" if entity == "parking" else "vehicle_rental"):
        return render(request, "booking/widget_denied.html", {"channel": None}, status=403)
    parking_form = PublicParkingReservationForm(request.POST or None, property_=selected)
    rental_form = PublicRentalBookingForm(request.POST or None, property_=selected)
    start, end = _parking_search_values(request)
    parking_form.fields["parking_lot"].queryset = selected.parking_lots.filter(
        is_active=True, booking_enabled=True
    )
    parking_form.fields["parking_space"].queryset = available_parking_spaces(
        property_=selected, start_at=start, end_at=end,
    )
    pickup, dropoff, vehicle_class = _rental_search_values(request)
    rental_form.fields["vehicle"].queryset = available_rental_vehicles(
        property_=selected, pickup_at=pickup, dropoff_at=dropoff, vehicle_class=vehicle_class,
    )
    rental_form.fields["rental_rate"].queryset = VehicleRentalRate.objects.filter(
        vehicle__property=selected, vehicle__is_active=True,
        vehicle__online_enabled=True, is_active=True,
    )
    active_form = rental_form if entity == "rentals" else parking_form
    if request.method == "POST" and active_form.is_valid():
        booking = active_form.save(commit=False)
        booking.property = selected
        booking.source = ParkingReservation.Source.ONLINE
        booking.status = (
            VehicleRentalBooking.Status.PENDING
            if entity == "rentals" else ParkingReservation.Status.PENDING
        )
        if entity == "rentals":
            _apply_rental_quote(booking)
            _apply_public_rental_consent(booking, active_form)
        elif booking.parking_lot_id:
            booking.amount = calculate_parking_quote(parking_lot=booking.parking_lot, start_at=booking.start_at, end_at=booking.end_at)
        if entity == "rentals":
            save_rental_booking(booking)
            _record_public_rental_consent(booking)
            queue_property_first_party_event(
                property_=selected, event_type="reservation_created",
                payload={"entity": "rentals", "booking_id": booking.id, "confirmation_code": booking.confirmation_code,
                         "status": booking.status, "vehicle_id": booking.vehicle_id, "total_amount": str(booking.total_amount),
                         "currency": booking.currency, "source": booking.source},
            )
        else:
            save_parking_reservation(booking)
            queue_property_first_party_event(
                property_=selected, event_type="reservation_created",
                payload={"entity": "parking", "booking_id": booking.id, "confirmation_code": booking.confirmation_code,
                         "status": booking.status, "parking_lot_id": booking.parking_lot_id, "amount": str(booking.amount),
                         "currency": booking.currency, "source": booking.source},
            )
        if entity == "rentals":
            queue_rental_notifications(booking)
            if booking.prepayment_amount:
                create_pending_rental_payment(booking=booking, amount=booking.prepayment_amount)
        payment_url = reverse("operations:rental_payment_checkout", kwargs={"payment_token": booking.payment_token}) if entity == "rentals" and booking.prepayment_amount else ""
        return render(request, "booking/online/fleet_widget.html", {
            "selected_property": selected, "entity": entity,
            "submitted": True, "booking": booking, "payment_url": payment_url,
            "manage_url": request.build_absolute_uri(reverse("operations:rental_booking_self_service", kwargs={"token": booking.public_manage_token})),
        })

    return render(request, "booking/online/fleet_widget.html", {
        "selected_property": selected, "entity": entity,
        "parking_form": parking_form, "rental_form": rental_form,
        "form": active_form,
        "parking_lots": parking_form.fields["parking_lot"].queryset,
        "vehicles": rental_form.fields["vehicle"].queryset.prefetch_related("photos"),
    })


@csrf_exempt
def fleet_availability_api(request, widget_key):
    """JSON availability endpoint for the web/mobile rental and parking engine."""
    selected = Property.objects.filter(fleet_widget_key=widget_key, is_active=True).first()
    if not selected or not _fleet_widget_origin_matches(request, selected):
        return JsonResponse({"detail": "Widget access denied."}, status=403)
    entity = request.GET.get("entity", "rentals")
    if _module_license_denied(request, selected, "parking" if entity == "parking" else "vehicle_rental"):
        return JsonResponse({"detail": "Module license inactive."}, status=403)
    if entity == "parking":
        start, end = _parking_search_values(request)
        lots = selected.parking_lots.filter(is_active=True, booking_enabled=True)
        spaces = available_parking_spaces(property_=selected, start_at=start, end_at=end)
        return JsonResponse({
            "entity": "parking",
            "lots": [{"id": lot.id, "code": lot.code, "name": lot.name, "currency": lot.currency} for lot in lots],
            "spaces": [{"id": space.id, "lot_id": space.parking_lot_id, "code": space.code, "type": space.space_type} for space in spaces],
        })
    pickup, dropoff, vehicle_class = _rental_search_values(request)
    vehicles = available_rental_vehicles(property_=selected, pickup_at=pickup, dropoff_at=dropoff, vehicle_class=vehicle_class).prefetch_related("photos", "rental_rates")
    return JsonResponse({
        "entity": "rentals",
        "vehicles": [{
            "id": vehicle.id, "code": vehicle.code, "name": vehicle.name,
            "class": vehicle.vehicle_class, "brand": vehicle.brand,
            "model": vehicle.model_name, "photos": [photo.image.url for photo in vehicle.photos.filter(show_online=True)],
            "rates": [{"id": rate.id, "name": rate.name, "daily": str(rate.daily_rate), "currency": rate.currency} for rate in vehicle.rental_rates.filter(is_active=True)],
        } for vehicle in vehicles],
    })


@csrf_exempt
def fleet_booking_api(request, widget_key):
    """Create a property-scoped pending fleet booking from JSON."""
    if request.method != "POST":
        return JsonResponse({"detail": "POST required."}, status=405)
    selected = Property.objects.filter(fleet_widget_key=widget_key, is_active=True).first()
    if not selected or not _fleet_widget_origin_matches(request, selected):
        return JsonResponse({"detail": "Widget access denied."}, status=403)
    try:
        payload = json.loads(request.body or b"{}")
    except (TypeError, ValueError):
        return JsonResponse({"detail": "Invalid JSON."}, status=400)
    entity = payload.get("entity", "rentals")
    if _module_license_denied(request, selected, "parking" if entity == "parking" else "vehicle_rental"):
        return JsonResponse({"detail": "Module license inactive."}, status=403)
    data = QueryDict("", mutable=True)
    for key, value in payload.items():
        if key == "extra_products" and isinstance(value, list):
            data.setlist(key, [str(item) for item in value])
        elif value is not None:
            data[key] = str(value)
    if entity == "rentals":
        defaults = {
            "status": VehicleRentalBooking.Status.PENDING, "source": ParkingReservation.Source.ONLINE,
            "daily_rate": "0", "total_amount": "0", "deposit_amount": "0", "currency": "TRY",
            "additional_driver_count": "0", "locale": "tr-TR", "prepayment_amount": "0",
        }
    else:
        defaults = {
            "status": ParkingReservation.Status.PENDING, "source": ParkingReservation.Source.ONLINE,
            "payment_status": ParkingReservation.PaymentStatus.UNPAID, "amount": "0", "currency": "TRY",
        }
    for key, value in defaults.items():
        data.setdefault(key, str(value))
    if entity == "parking":
        form = PublicParkingReservationForm(data=data, property_=selected)
    else:
        form = PublicRentalBookingForm(data=data, property_=selected)
    if not form.is_valid():
        return JsonResponse({"detail": "Invalid booking.", "errors": form.errors.get_json_data()}, status=400)
    booking = form.save(commit=False)
    booking.property = selected
    booking.source = ParkingReservation.Source.ONLINE
    booking.status = ParkingReservation.Status.PENDING if entity == "parking" else VehicleRentalBooking.Status.PENDING
    if entity == "parking" and booking.parking_lot_id:
        booking.amount = calculate_parking_quote(parking_lot=booking.parking_lot, start_at=booking.start_at, end_at=booking.end_at)
    elif entity == "rentals":
        _apply_rental_quote(booking)
        _apply_public_rental_consent(booking, form)
    if entity == "rentals":
        save_rental_booking(booking)
        _record_public_rental_consent(booking)
        queue_property_first_party_event(
            property_=selected, event_type="reservation_created",
            payload={"entity": "rentals", "booking_id": booking.id, "confirmation_code": booking.confirmation_code,
                     "status": booking.status, "vehicle_id": booking.vehicle_id, "total_amount": str(booking.total_amount),
                     "currency": booking.currency, "source": booking.source},
        )
    else:
        save_parking_reservation(booking)
        queue_property_first_party_event(
            property_=selected, event_type="reservation_created",
            payload={"entity": "parking", "booking_id": booking.id, "confirmation_code": booking.confirmation_code,
                     "status": booking.status, "parking_lot_id": booking.parking_lot_id, "amount": str(booking.amount),
                     "currency": booking.currency, "source": booking.source},
        )
    if entity == "rentals":
        queue_rental_notifications(booking)
        if booking.prepayment_amount:
            create_pending_rental_payment(booking=booking, amount=booking.prepayment_amount)
    response = {"entity": entity, "confirmation_code": booking.confirmation_code, "status": booking.status}
    if entity == "rentals" and booking.prepayment_amount:
        response["payment_url"] = request.build_absolute_uri(reverse("operations:rental_payment_checkout", kwargs={"payment_token": booking.payment_token}))
    return JsonResponse(response, status=201)


@csrf_exempt
def fleet_channel_webhook(request, widget_key):
    """Receive signed channel-manager events without exposing booking secrets."""
    if request.method != "POST":
        return JsonResponse({"detail": "POST required."}, status=405)
    selected = Property.objects.filter(fleet_widget_key=widget_key, is_active=True).first()
    secret = getattr(django_settings, "FLEET_CHANNEL_WEBHOOK_SECRET", "")
    signature = request.headers.get("X-Fleet-Signature", "")
    expected = hmac.new(secret.encode(), request.body, hashlib.sha256).hexdigest() if secret else ""
    if not selected or not secret or not signature or not hmac.compare_digest(expected, signature):
        return JsonResponse({"detail": "Invalid webhook."}, status=403)
    try:
        payload = json.loads(request.body or b"{}")
    except (TypeError, ValueError):
        return JsonResponse({"detail": "Invalid JSON."}, status=400)
    webhook_event, created = _register_fleet_webhook(selected, "channel_manager", payload)
    if not created:
        return JsonResponse({"received": True, "duplicate": True, "event_id": webhook_event.id})
    event = RentalChannelSyncEvent.objects.create(
        property=selected,
        channel=str(payload.get("channel") or "unknown")[:80],
        event_type=str(payload.get("event_type") or "inventory_update")[:40],
        external_reference=str(payload.get("external_reference") or "")[:180],
        status=str(payload.get("status") or "received")[:20],
        payload=payload,
        error_message=str(payload.get("error_message") or "")[:4000],
    )
    _complete_fleet_webhook(webhook_event)
    return JsonResponse({"received": True, "event_id": event.id})


def _signed_fleet_payload(request, widget_key):
    """Validate a fleet integration payload and return (property, payload, error)."""
    if request.method != "POST":
        return None, None, JsonResponse({"detail": "POST required."}, status=405)
    selected = Property.objects.filter(fleet_widget_key=widget_key, is_active=True).first()
    secret = getattr(django_settings, "FLEET_CHANNEL_WEBHOOK_SECRET", "")
    signature = request.headers.get("X-Fleet-Signature", "")
    expected = hmac.new(secret.encode(), request.body, hashlib.sha256).hexdigest() if secret else ""
    if not selected or not secret or not signature or not hmac.compare_digest(expected, signature):
        return None, None, JsonResponse({"detail": "Invalid webhook."}, status=403)
    try:
        payload = json.loads(request.body or b"{}")
    except (TypeError, ValueError):
        return None, None, JsonResponse({"detail": "Invalid JSON."}, status=400)
    return selected, payload, None


def _register_fleet_webhook(property_, provider, payload):
    """Register a verified webhook and report whether it is a duplicate."""
    event_id = str(payload.get("event_id") or payload.get("id") or "").strip()
    if not event_id:
        event_id = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
    event, created = WebhookEvent.objects.get_or_create(
        property=property_, provider=provider, event_id=event_id,
        defaults={
            "event_type": str(payload.get("event_type") or "")[:80],
            "signature_verified": True,
            "payload": payload,
        },
    )
    return event, created


def _complete_fleet_webhook(event):
    event.status = "processed"
    event.processed_at = timezone.now()
    event.save(update_fields=["status", "processed_at"])


def _fail_fleet_webhook(event, message):
    event.status = "rejected"
    event.error_message = str(message)[:4000]
    event.processed_at = timezone.now()
    event.save(update_fields=["status", "error_message", "processed_at"])


@csrf_exempt
def fleet_telemetry_webhook(request, widget_key):
    selected, payload, error = _signed_fleet_payload(request, widget_key)
    if error:
        return error
    webhook_event, created = _register_fleet_webhook(selected, "telematics", payload)
    if not created:
        return JsonResponse({"received": True, "duplicate": True, "event_id": webhook_event.id})
    vehicle = selected.vehicles.filter(
        Q(id=payload.get("vehicle_id")) | Q(code=str(payload.get("vehicle_code") or ""))
    ).first()
    if not vehicle:
        return JsonResponse({"detail": "Vehicle not found."}, status=404)
    occurred_at = parse_datetime(str(payload.get("occurred_at") or "")) or timezone.now()
    event = VehicleTelemetryEvent.objects.create(
        property=selected, vehicle=vehicle, source=str(payload.get("source") or "telematics")[:80],
        occurred_at=occurred_at, latitude=payload.get("latitude"), longitude=payload.get("longitude"),
        mileage=payload.get("mileage"), speed=payload.get("speed"), payload=payload,
    )
    _complete_fleet_webhook(webhook_event)
    return JsonResponse({"received": True, "event_id": event.id})


@csrf_exempt
def fleet_parking_device_webhook(request, widget_key):
    selected, payload, error = _signed_fleet_payload(request, widget_key)
    if error:
        return error
    webhook_event, created = _register_fleet_webhook(selected, "parking_device", payload)
    if not created:
        return JsonResponse({"received": True, "duplicate": True, "event_id": webhook_event.id})
    device = selected.parking_devices.filter(is_active=True).filter(
        Q(id=payload.get("device_id")) | Q(name=str(payload.get("device_name") or ""))
    ).first()
    if not device:
        _fail_fleet_webhook(webhook_event, "Active parking device not found.")
        return JsonResponse({"detail": "Parking device not found."}, status=404)
    kind = str(payload.get("event_type") or "").strip().lower()
    if kind not in {ParkingAccessEvent.Kind.ENTRY, ParkingAccessEvent.Kind.EXIT}:
        _fail_fleet_webhook(webhook_event, "event_type must be entry or exit.")
        return JsonResponse({"detail": "Invalid parking event type."}, status=400)
    parking_space = device.parking_lot.spaces.filter(is_active=True).filter(
        Q(id=payload.get("parking_space_id")) | Q(code=str(payload.get("parking_space_code") or ""))
    ).first() if device.parking_lot_id else None
    device.last_seen_at = timezone.now()
    device.save(update_fields=["last_seen_at"])
    event = ParkingAccessEvent.objects.create(
        property=selected, parking_lot=device.parking_lot,
        parking_space=parking_space,
        kind=kind,
        vehicle_plate=str(payload.get("plate_number") or "")[:32],
        occurred_at=parse_datetime(str(payload.get("occurred_at") or "")) or timezone.now(),
        anpr_reference=f"device:{device.id}", metadata=payload,
    )
    _complete_fleet_webhook(webhook_event)
    return JsonResponse({"received": True, "event_id": event.id})


@csrf_exempt
def fleet_flight_webhook(request, widget_key):
    selected, payload, error = _signed_fleet_payload(request, widget_key)
    if error:
        return error
    webhook_event, created = _register_fleet_webhook(selected, "flight_provider", payload)
    if not created:
        return JsonResponse({"received": True, "duplicate": True, "event_id": webhook_event.id})
    booking = selected.vehicle_rental_bookings.filter(
        Q(id=payload.get("booking_id")) | Q(confirmation_code=str(payload.get("confirmation_code") or ""))
    ).first()
    if not booking:
        return JsonResponse({"detail": "Rental booking not found."}, status=404)
    status_obj, _ = RentalFlightStatus.objects.update_or_create(
        booking=booking,
        defaults={
            "flight_number": str(payload.get("flight_number") or "")[:40],
            "airport_code": str(payload.get("airport_code") or "")[:8],
            "scheduled_arrival_at": parse_datetime(str(payload.get("scheduled_arrival_at") or "")),
            "estimated_arrival_at": parse_datetime(str(payload.get("estimated_arrival_at") or "")),
            "status": str(payload.get("status") or "unknown")[:32],
            "source": str(payload.get("source") or "flight_provider")[:80],
            "last_checked_at": timezone.now(), "payload": payload,
        },
    )
    _complete_fleet_webhook(webhook_event)
    return JsonResponse({"received": True, "flight_status_id": status_obj.id})


def rental_payment_checkout(request, payment_token):
    booking = VehicleRentalBooking.objects.select_related("property").filter(
        payment_token=payment_token, property__is_active=True,
    ).first()
    if not booking:
        return JsonResponse({"detail": "Rental booking not found."}, status=404)
    gateway = booking.property.payment_gateways.filter(active=True).order_by("-default_gate", "id").first()
    if not gateway:
        return JsonResponse({"detail": "No active payment gateway is configured."}, status=503)
    try:
        _, result = start_rental_checkout(
            booking=booking, gateway=gateway,
            success_url=request.build_absolute_uri(reverse("operations:rental_payment_result", kwargs={"payment_token": payment_token})),
            cancel_url=request.build_absolute_uri(reverse("operations:rental_payment_result", kwargs={"payment_token": payment_token})),
        )
    except (PaymentConfigurationError, PaymentProviderError) as exc:
        return JsonResponse({"detail": str(exc)}, status=503)
    if result.get("checkout_method") == "post":
        return HttpResponse(render_checkout(result), content_type="text/html; charset=utf-8")
    return redirect(result["checkout_url"])


@csrf_exempt
def rental_payment_result(request, payment_token):
    booking = VehicleRentalBooking.objects.select_related("property").filter(payment_token=payment_token, property__is_active=True).first()
    if not booking:
        return JsonResponse({"detail": "Rental booking not found."}, status=404)
    payment = booking.payments.order_by("-created_at").first()
    if request.method == "POST" and payment and payment.gateway:
        provider = (payment.gateway.payment_model or "").strip().lower()
        payload = request.POST
        if provider == "nestpay_halkbank":
            store_key = (payment.gateway.configuration or {}).get("store_key_env", "")
            store_key = __import__("os").environ.get(store_key, "") if store_key else getattr(django_settings, "PAYMENT_NESTPAY_STORE_KEY", "")
            verified = verify_nestpay_response(payload, store_key)
        elif provider == "cpay_stb":
            password_env = (payment.gateway.configuration or {}).get("merchant_password_env", "")
            password = __import__("os").environ.get(password_env, "") if password_env else getattr(django_settings, "PAYMENT_CPAY_MERCHANT_PASSWORD", "")
            verified = verify_cpay_response(payload, password)
        else:
            verified = False
        if not verified:
            payment.status = RentalPayment.Status.FAILED
            payment.metadata = {**(payment.metadata or {}), "provider_result": dict(payload), "verification": "failed"}
            payment.save(update_fields=["status", "metadata", "updated_at"])
            return JsonResponse({"detail": "Payment verification failed."}, status=400)
        payment.status = RentalPayment.Status.CAPTURED
        payment.provider_reference = (
            payload.get("TransId") or payload.get("cPayPaymentRef") or payment.provider_reference
        )[:180]
        payment.metadata = {**(payment.metadata or {}), "provider_result": dict(payload), "verification": "passed"}
        payment.save(update_fields=["status", "provider_reference", "metadata", "updated_at"])
    return JsonResponse({"booking": booking.confirmation_code, "payment_status": payment.status if payment else "unpaid"})


@csrf_exempt
def rental_payment_webhook(request):
    if request.method != "POST" or not django_settings.PAYMENT_STRIPE_WEBHOOK_SECRET:
        return JsonResponse({"detail": "Webhook is not configured."}, status=400)
    signature = request.headers.get("Stripe-Signature", "")
    timestamp = next((part.split("=", 1)[1] for part in signature.split(",") if part.startswith("t=")), "")
    signatures = [part.split("=", 1)[1] for part in signature.split(",") if part.startswith("v1=")]
    expected = hmac.new(django_settings.PAYMENT_STRIPE_WEBHOOK_SECRET.encode(), f"{timestamp}.".encode() + request.body, hashlib.sha256).hexdigest()
    if not timestamp or not any(hmac.compare_digest(expected, value) for value in signatures):
        return JsonResponse({"detail": "Invalid signature."}, status=400)
    try:
        event = json.loads(request.body)
        external_id = event.get("data", {}).get("object", {}).get("id", "")
        payment = RentalPayment.objects.get(provider_reference=external_id)
    except (ValueError, RentalPayment.DoesNotExist):
        return JsonResponse({"detail": "Unknown rental payment."}, status=400)
    if event.get("type") == "checkout.session.completed":
        payment.status = RentalPayment.Status.CAPTURED
        payment.metadata = event
        payment.save(update_fields=["status", "metadata", "updated_at"])
    return JsonResponse({"received": True})


@login_required
def front_cash(request):
    properties, selected, denied = _finance_context(request)
    if denied:
        return denied
    shift_form = CashierShiftForm(request.POST or None, prefix="shift")
    transaction_form = FrontCashTransactionForm(request.POST or None, prefix="transaction")
    if request.method == "POST" and selected:
        action = request.POST.get("action")
        if action == "transaction" and transaction_form.is_valid():
            transaction = transaction_form.save(commit=False)
            transaction.property = selected
            transaction.posted_by = request.user
            transaction.save()
            messages.success(request, "Kasa hareketi kaydedildi.")
        elif action == "open_shift" and shift_form.is_valid():
            shift = shift_form.save(commit=False)
            shift.property = selected
            shift.cashier = request.user
            shift.status = CashierShift.Status.OPEN
            shift.save()
            messages.success(request, "Ön kasa vardiyası açıldı.")
        elif action == "close_shift":
            shift = selected.cashier_shifts.filter(status=CashierShift.Status.OPEN, cashier=request.user).first()
            if shift:
                shift.closing_balance = request.POST.get("closing_balance") or None
                shift.closing_note = request.POST.get("closing_note", "").strip()
                shift.closed_at = timezone.now()
                shift.closed_by = request.user
                shift.status = CashierShift.Status.CLOSED
                shift.save(update_fields=["closing_balance", "closing_note", "closed_at", "closed_by", "status"])
                messages.success(request, "Ön kasa vardiyası kapatıldı.")
            else:
                messages.error(request, "Kapatılacak açık vardiya bulunamadı.")
        return redirect(f"{reverse('operations:front_cash')}?property_id={selected.id}")
    shifts = selected.cashier_shifts.select_related("cashier", "closed_by")[:50] if selected else CashierShift.objects.none()
    transactions = selected.front_cash_transactions.select_related("posted_by", "guest")[:50] if selected else FrontCashTransaction.objects.none()
    open_shift = selected.cashier_shifts.filter(status=CashierShift.Status.OPEN, cashier=request.user).first() if selected else None
    return render(request, "booking/operations/front_cash.html", {
        "title": "Ön Kasa", "properties": properties, "selected_property": selected,
        "shift_form": shift_form, "transaction_form": transaction_form, "shifts": shifts, "transactions": transactions, "open_shift": open_shift,
    })


@login_required
def invoices(request):
    properties, selected, denied = _finance_context(request)
    if denied:
        return denied
    form = InvoiceForm(request.POST or None, initial={"issue_date": timezone.localdate(), "currency": "TRY"})
    if request.method == "POST" and selected and form.is_valid():
        invoice = form.save(commit=False)
        invoice.property = selected
        invoice.created_by = request.user
        invoice.save()
        messages.success(request, "Fatura taslağı kaydedildi.")
        return redirect(f"{reverse('operations:invoice_detail', args=[invoice.id])}?property_id={selected.id}")
    qs = selected.invoices.select_related("reservation", "created_by") if selected else Invoice.objects.none()
    query = request.GET.get("q", "").strip()
    if query:
        qs = qs.filter(Q(number__icontains=query) | Q(customer_name__icontains=query))
    return render(request, "booking/operations/invoices.html", {"title": "Fatura Listesi", "properties": properties, "selected_property": selected, "form": form, "invoices": qs[:250], "query": query})


@login_required
def invoice_detail(request, invoice_id):
    properties, selected, denied = _finance_context(request)
    if denied:
        return denied
    invoice = selected.invoices.filter(id=invoice_id).first() if selected else None
    if not invoice:
        return HttpResponse("Fatura bulunamadı.", status=404)
    form = InvoiceForm(request.POST or None, instance=invoice)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Fatura kaydedildi.")
        return redirect(request.get_full_path())
    return render(request, "booking/operations/invoice_detail.html", {"title": "Fatura Detayı", "properties": properties, "selected_property": selected, "invoice": invoice, "form": form})


@login_required
def invoice_preview(request, invoice_id):
    properties, selected, denied = _finance_context(request)
    if denied:
        return denied
    invoice = selected.invoices.filter(id=invoice_id).first() if selected else None
    if not invoice:
        return HttpResponse("Fatura bulunamadı.", status=404)
    return render(request, "booking/operations/invoice_preview.html", {"title": "Fatura Önizleme", "properties": properties, "selected_property": selected, "invoice": invoice})


@login_required
def payment_gateways(request):
    properties, selected, denied = _finance_context(request)
    if denied:
        return denied
    form = PaymentGatewayForm(request.POST or None)
    if request.method == "POST" and selected and form.is_valid():
        gateway = form.save(commit=False)
        gateway.property = selected
        if gateway.default_gate:
            selected.payment_gateways.update(default_gate=False)
        gateway.save()
        messages.success(request, "Ödeme geçidi kaydedildi.")
        return redirect(f"{reverse('operations:payment_gateways')}?property_id={selected.id}")
    gateways = selected.payment_gateways.all() if selected else PaymentGateway.objects.none()
    return render(request, "booking/operations/payment_gateways.html", {"title": "Ödeme Geçitleri", "properties": properties, "selected_property": selected, "form": form, "gateways": gateways})


@login_required
def payment_gateway_detail(request, gateway_id):
    properties, selected, denied = _finance_context(request)
    if denied:
        return denied
    gateway = selected.payment_gateways.filter(id=gateway_id).first() if selected else None
    if not gateway:
        return HttpResponse("Ödeme geçidi bulunamadı.", status=404)
    form = PaymentGatewayForm(request.POST or None, instance=gateway)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        if obj.default_gate:
            selected.payment_gateways.exclude(id=obj.id).update(default_gate=False)
        obj.save()
        messages.success(request, "Ödeme geçidi güncellendi.")
        return redirect(request.get_full_path())
    return render(request, "booking/operations/payment_gateway_detail.html", {"title": "Ödeme Geçidi Detayı", "properties": properties, "selected_property": selected, "gateway": gateway, "form": form})


@login_required
def night_audit(request):
    properties, selected, denied = _finance_context(request)
    if denied:
        return denied
    if request.method == "POST" and selected:
        today = timezone.localdate()
        run = NightAuditRun.objects.create(property=selected, audit_date=today, status=NightAuditRun.Status.COMPLETED, completed_at=timezone.now(), actor=request.user, summary={"reservations": selected.reservations.count(), "arrivals": selected.reservations.filter(check_in=today).count(), "departures": selected.reservations.filter(check_out=today).count()})
        messages.success(request, f"Gün sonu tamamlandı: {run.audit_date}.")
        return redirect(f"{reverse('operations:night_audit')}?property_id={selected.id}")
    runs = selected.night_audit_runs.select_related("actor")[:100] if selected else NightAuditRun.objects.none()
    return render(request, "booking/operations/night_audit.html", {"title": "Gün Sonu / Night Audit", "properties": properties, "selected_property": selected, "runs": runs})


@login_required
def agencies(request):
    properties, selected = _selected_property(request)
    if _permission_denied(request, selected, "operations.front_office.manage"):
        return HttpResponseForbidden("Bu tesis için acente yetkiniz yok.")
    form = AgencyForm(request.POST or None)
    if request.method == "POST" and selected and form.is_valid():
        agency = form.save(commit=False)
        agency.property = selected
        agency.save()
        messages.success(request, "Acente kaydedildi.")
        return redirect(f"{reverse('operations:agencies')}?property_id={selected.id}")
    agencies_qs = selected.agencies.all() if selected else Agency.objects.none()
    return render(request, "booking/operations/agencies.html", {"title": "Acente Yönetimi", "properties": properties, "selected_property": selected, "form": form, "agencies": agencies_qs})


@login_required
def call_requests(request):
    properties, selected = _selected_property(request)
    if _permission_denied(request, selected, "operations.front_office.manage"):
        return HttpResponseForbidden("Bu tesis için çağrı listesi yetkiniz yok.")
    form = FrontOfficeCallRequestForm(request.POST or None)
    if request.method == "POST" and selected:
        action = request.POST.get("action")
        if action == "create" and form.is_valid():
            obj = form.save(commit=False); obj.property = selected; obj.created_by = request.user; obj.save(); messages.success(request, "Çağrı talebi kaydedildi.")
        elif action == "status":
            obj = selected.front_office_call_requests.filter(id=request.POST.get("call_id")).first()
            status = request.POST.get("status")
            if obj and status in dict(FrontOfficeCallRequest.Status.choices):
                obj.status = status; obj.save(update_fields=["status", "updated_at"]); messages.success(request, "Çağrı durumu güncellendi.")
        return redirect(f"{reverse('operations:call_requests')}?property_id={selected.id}")
    calls = selected.front_office_call_requests.select_related("guest", "reservation", "created_by") if selected else FrontOfficeCallRequest.objects.none()
    return render(request, "booking/operations/call_requests.html", {"title": "Çağrı Listesi", "properties": properties, "selected_property": selected, "form": form, "calls": calls[:250], "status_choices": FrontOfficeCallRequest.Status.choices})


@login_required
def support_center(request):
    properties, selected, denied = _support_context(request)
    if denied:
        return HttpResponseForbidden("Bu tesis için destek merkezi yetkiniz yok.")
    ticket_form = SupportTicketForm(request.POST or None, prefix="ticket")
    reply_form = SupportReplyForm(request.POST or None, prefix="reply")
    ticket_id = request.POST.get("ticket_id") or request.GET.get("ticket_id")
    selected_ticket = SupportTicket.objects.filter(property=selected, id=ticket_id).prefetch_related("messages__author", "audit_events__actor").first() if selected and ticket_id else None
    if request.method == "POST" and selected:
        action = request.POST.get("action")
        if action == "ticket":
            ticket_form = SupportTicketForm(request.POST, request.FILES, prefix="ticket")
            if ticket_form.is_valid():
                ticket = ticket_form.save(commit=False)
                ticket.property = selected
                ticket.created_by = request.user
                ticket.save()
                SupportAuditEvent.objects.create(ticket=ticket, actor=request.user, event="created")
                messages.success(request, "Destek talebi oluşturuldu.")
                return redirect(f"{reverse('operations:support_center')}?property_id={selected.id}&ticket_id={ticket.id}")
        elif action == "reply" and selected_ticket:
            reply_form = SupportReplyForm(request.POST, prefix="reply")
            if reply_form.is_valid():
                reply = reply_form.save(commit=False)
                reply.ticket = selected_ticket
                reply.author = request.user
                reply.save()
                selected_ticket.status = SupportTicket.Status.OPEN if reply.is_internal else SupportTicket.Status.PENDING_STAFF
                selected_ticket.save(update_fields=["status", "updated_at"])
                SupportAuditEvent.objects.create(ticket=selected_ticket, actor=request.user, event="replied", metadata={"internal": reply.is_internal})
                messages.success(request, "Yanıt kaydedildi.")
                return redirect(f"{reverse('operations:support_center')}?property_id={selected.id}&ticket_id={selected_ticket.id}")
        elif action == "status" and selected_ticket:
            status = request.POST.get("status")
            if status in dict(SupportTicket.Status.choices):
                selected_ticket.status = status
                selected_ticket.resolved_at = timezone.now() if status in {SupportTicket.Status.RESOLVED, SupportTicket.Status.CLOSED} else None
                selected_ticket.save(update_fields=["status", "resolved_at", "updated_at"])
                SupportAuditEvent.objects.create(ticket=selected_ticket, actor=request.user, event="status_changed", metadata={"status": status})
                messages.success(request, "Talep durumu güncellendi.")
                return redirect(request.get_full_path())
    tickets = SupportTicket.objects.filter(property=selected).select_related("created_by", "assigned_to")[:100] if selected else SupportTicket.objects.none()
    return render(request, "booking/operations/support_center.html", {"title": "Destek Merkezi", "properties": properties, "selected_property": selected, "tickets": tickets, "selected_ticket": selected_ticket, "ticket_form": ticket_form, "reply_form": reply_form, "status_choices": SupportTicket.Status.choices, "help_links": selected.support_help_links.filter(is_active=True) if selected else SupportHelpLink.objects.none()})


@login_required
def support_faq(request):
    properties, selected, denied = _support_context(request)
    if denied:
        return HttpResponseForbidden("Bu tesis için FAQ yetkiniz yok.")
    if request.method == "POST":
        return HttpResponseForbidden("FAQ içerikleri yalnızca sistem yöneticisi tarafından yönetilebilir.")
    query = request.GET.get("q", "")
    faqs = selected.support_faq_items.select_related("category").filter(is_active=True) if selected else SupportFAQItem.objects.none()
    if query:
        faqs = faqs.filter(Q(question__icontains=query) | Q(answer__icontains=query))
    return render(request, "booking/operations/support_faq.html", {"title": "FAQ ve Yardım", "properties": properties, "selected_property": selected, "categories": selected.support_faq_categories.filter(is_active=True) if selected else SupportFAQCategory.objects.none(), "faqs": faqs, "query": query})


@login_required
def support_education(request):
    properties, selected, denied = _support_context(request)
    if denied:
        return HttpResponseForbidden("Bu tesis için eğitim talebi yetkiniz yok.")
    form = SupportEducationRequestForm(request.POST or None)
    if request.method == "POST" and selected and form.is_valid():
        obj = form.save(commit=False); obj.property = selected; obj.user = request.user; obj.save(); messages.success(request, "Eğitim talebiniz alındı."); return redirect(f"{reverse('operations:support_education')}?property_id={selected.id}")
    requests = selected.support_education_requests.filter(user=request.user) if selected else SupportEducationRequest.objects.none()
    return render(request, "booking/operations/support_education.html", {"title": "Eğitim Talebi", "properties": properties, "selected_property": selected, "form": form, "requests": requests})


@login_required
def support_referral(request):
    properties, selected, denied = _support_context(request)
    if denied:
        return HttpResponseForbidden("Bu tesis için referral yetkiniz yok.")
    form = SupportReferralForm(request.POST or None)
    if request.method == "POST" and selected and form.is_valid():
        obj = form.save(commit=False); obj.property = selected; obj.referrer = request.user; obj.save(); messages.success(request, "Öneri kaydedildi."); return redirect(f"{reverse('operations:support_referral')}?property_id={selected.id}")
    referrals = selected.support_referrals.filter(referrer=request.user) if selected else SupportReferral.objects.none()
    return render(request, "booking/operations/support_referral.html", {"title": "Davet Et ve Kazan", "properties": properties, "selected_property": selected, "form": form, "referrals": referrals})


@login_required
def support_video(request):
    properties, selected, denied = _support_context(request)
    if denied:
        return HttpResponseForbidden("Bu tesis için video kütüphanesi yetkiniz yok.")
    categories = selected.support_video_categories.prefetch_related("videos") if selected else SupportVideoCategory.objects.none()
    return render(request, "booking/operations/support_video.html", {"title": "Video Kütüphanesi", "properties": properties, "selected_property": selected, "categories": categories})


def _can_manage_user_mfa(request, property_):
    if not property_ or request.user.is_superuser:
        return True
    return UserPropertyAccess.objects.filter(
        user=request.user, property=property_, is_active=True, role__is_active=True,
    ).filter(Q(valid_from__isnull=True) | Q(valid_from__lte=timezone.localdate())) \
     .filter(Q(valid_until__isnull=True) | Q(valid_until__gte=timezone.localdate())) \
     .filter(role__name__iregex=r"^(hotel[ _-]?owner|hotel[ _-]?manager)$").exists()


@login_required
def dashboard(request):
    properties, selected = _selected_property(request)
    if _permission_denied(request, selected, "operations.dashboard.view"):
        return HttpResponseForbidden("Bu tesis için dashboard erişiminiz yok.")
    today = timezone.localdate()
    if selected:
        rooms_total = selected.units.filter(is_active=True).count()
        occupied = ReservationItem.objects.filter(
            reservation__property=selected,
            reservation__status__in=[ReservationStatus.PENDING, ReservationStatus.CONFIRMED],
            reservation__check_in__lte=today,
            reservation__check_out__gt=today,
            unit__isnull=False,
        ).count()
        metrics = {
            "rooms_total": rooms_total,
            "occupied": occupied,
            "occupancy_percent": round((occupied / rooms_total) * 100, 1) if rooms_total else 0,
            "dirty": HousekeepingTask.objects.filter(property=selected, status=HousekeepingStatus.DIRTY).count(),
            "maintenance": MaintenanceTicket.objects.filter(property=selected, status__in=[MaintenanceStatus.OPEN, MaintenanceStatus.IN_PROGRESS, MaintenanceStatus.WAITING]).count(),
            "tasks": OperationalTask.objects.filter(property=selected, status__in=[TaskStatus.OPEN, TaskStatus.IN_PROGRESS, TaskStatus.WAITING]).count(),
            "overdue_sla": OperationalTask.objects.filter(property=selected, sla_due_at__lt=timezone.now(), status__in=[TaskStatus.OPEN, TaskStatus.IN_PROGRESS, TaskStatus.WAITING]).count(),
            "overdue_maintenance": MaintenanceTicket.objects.filter(property=selected, sla_due_at__lt=timezone.now(), status__in=[MaintenanceStatus.OPEN, MaintenanceStatus.IN_PROGRESS, MaintenanceStatus.WAITING]).count(),
            "guests": Guest.objects.filter(property=selected).count(),
            "arrivals": ReservationItem.objects.filter(reservation__property=selected, reservation__check_in=today).count(),
            "departures": ReservationItem.objects.filter(reservation__property=selected, reservation__check_out=today).count(),
        }
        recent_tasks = OperationalTask.objects.filter(property=selected).select_related("assigned_to")[:8]
        recent_tickets = MaintenanceTicket.objects.filter(property=selected).select_related("unit")[:8]
    else:
        metrics = {key: 0 for key in ["rooms_total", "occupied", "occupancy_percent", "dirty", "maintenance", "tasks", "overdue_sla", "overdue_maintenance", "guests", "arrivals", "departures"]}
        recent_tasks = OperationalTask.objects.none()
        recent_tickets = MaintenanceTicket.objects.none()
    return render(request, "booking/operations/dashboard.html", {
        "title": "Hotel Dashboard", "properties": properties, "selected_property": selected,
        "metrics": metrics, "recent_tasks": recent_tasks, "recent_tickets": recent_tickets, "today": today,
    })


@login_required
def reports(request):
    properties, selected = _selected_property(request)
    if _permission_denied(request, selected, "operations.reports.view"):
        return HttpResponseForbidden("Bu tesis için rapor erişiminiz yok.")
    today = timezone.localdate()
    start = parse_date(request.GET.get("start", "")) or today.replace(day=1)
    end = parse_date(request.GET.get("end", "")) or today
    if end < start:
        start, end = end, start
    reservations = ReservationItem.objects.filter(
        reservation__property=selected,
        reservation__status__in=[ReservationStatus.PENDING, ReservationStatus.CONFIRMED, ReservationStatus.COMPLETED],
        reservation__check_in__lt=end + timedelta(days=1),
        reservation__check_out__gt=start,
    ).select_related("reservation", "reservation__guest", "unit", "unit_type") if selected else ReservationItem.objects.none()
    room_nights = 0
    for item in reservations:
        overlap_start = max(item.reservation.check_in, start)
        overlap_end = min(item.reservation.check_out, end + timedelta(days=1))
        room_nights += max(0, (overlap_end - overlap_start).days) * item.quantity
    reservation_headers = reservations.values("reservation_id").distinct()
    revenue = Reservation.objects.filter(id__in=reservation_headers).aggregate(total=Sum("total_amount"))["total"] or 0
    rooms = selected.units.filter(is_active=True).count() if selected else 0
    available_nights = rooms * ((end - start).days + 1)
    metrics = {
        "reservations": reservation_headers.count(), "room_nights": room_nights,
        "revenue": revenue, "arrivals": Reservation.objects.filter(property=selected, check_in__range=(start, end)).count() if selected else 0,
        "departures": Reservation.objects.filter(property=selected, check_out__range=(start, end)).count() if selected else 0,
        "occupancy": round((room_nights / available_nights) * 100, 1) if available_nights else 0,
    }
    if request.GET.get("format") == "csv":
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="hotel-report-{start.isoformat()}-{end.isoformat()}.csv"'
        response.write("Metrik,Değer\n")
        for label, value in (("Başlangıç", start), ("Bitiş", end), ("Rezervasyon", metrics["reservations"]), ("Oda gece", room_nights), ("Gelir", revenue), ("Doluluk %", metrics["occupancy"]), ("Giriş", metrics["arrivals"]), ("Çıkış", metrics["departures"])):
            response.write(f'"{label}","{value}"\n')
        return response
    return render(request, "booking/operations/reports.html", {
        "title": "Otel Raporları", "properties": properties, "selected_property": selected,
        "start": start, "end": end, "metrics": metrics,
    })


@login_required
def housekeeping(request):
    properties, selected = _selected_property(request)
    if _permission_denied(request, selected, "operations.housekeeping.manage"):
        return HttpResponseForbidden("Bu tesis için housekeeping erişiminiz yok.")
    if request.method == "POST" and selected:
        task = HousekeepingTask.objects.filter(property=selected, id=request.POST.get("task_id")).first()
        unit = selected.units.filter(id=request.POST.get("unit_id")).first()
        if request.POST.get("action") == "create" and unit:
            due_at = parse_datetime(request.POST.get("due_at", "")) if request.POST.get("due_at") else None
            if due_at and timezone.is_naive(due_at):
                due_at = timezone.make_aware(due_at)
            new_task = HousekeepingTask.objects.create(
                property=selected, unit=unit,
                status=request.POST.get("status", HousekeepingStatus.DIRTY),
                priority=request.POST.get("priority", TaskPriority.NORMAL),
                assigned_to_id=request.POST.get("assigned_to") or None,
                shift=request.POST.get("shift", "").strip(),
                note=request.POST.get("note", ""),
                due_at=due_at,
            )
            HousekeepingTaskHistory.objects.create(
                task=new_task, property=selected, unit=unit, status=new_task.status,
                shift=new_task.shift, note=new_task.note, assigned_to=new_task.assigned_to,
                changed_by=request.user,
            )
            UnitHousekeepingState.objects.update_or_create(
                unit=unit,
                defaults={"status": request.POST.get("status", HousekeepingStatus.DIRTY), "note": request.POST.get("note", ""), "changed_by": request.user},
            )
        elif task and request.POST.get("action") == "status":
            status = request.POST.get("status")
            if status in HousekeepingStatus.values:
                task.status = status
                task.assigned_to_id = request.POST.get("assigned_to") or task.assigned_to_id
                task.shift = request.POST.get("shift", task.shift).strip()
                task.note = request.POST.get("note", task.note)
                task.inspected_at = timezone.now() if status in {HousekeepingStatus.INSPECTION, HousekeepingStatus.CLEAN} else task.inspected_at
                task.inspected_by = request.user if status in {HousekeepingStatus.INSPECTION, HousekeepingStatus.CLEAN} else task.inspected_by
                task.save(update_fields=["status", "assigned_to", "shift", "note", "inspected_at", "inspected_by", "updated_at"])
                HousekeepingTaskHistory.objects.create(
                    task=task, property=selected, unit=task.unit, status=task.status,
                    shift=task.shift, note=task.note, assigned_to=task.assigned_to,
                    changed_by=request.user,
                )
                UnitHousekeepingState.objects.update_or_create(
                    unit=task.unit,
                    defaults={"status": status, "note": task.note, "changed_by": request.user},
                )
        elif task and request.POST.get("action") == "approve":
            task.supervisor_approved_at = timezone.now()
            task.supervisor_approved_by = request.user
            task.save(update_fields=["supervisor_approved_at", "supervisor_approved_by", "updated_at"])
            HousekeepingTaskHistory.objects.create(
                task=task, property=selected, unit=task.unit, status=task.status,
                shift=task.shift, note="Supervisor onayı", assigned_to=task.assigned_to,
                changed_by=request.user,
            )
        return redirect(f"{reverse('operations:housekeeping')}?property_id={selected.id}")
    tasks_qs = HousekeepingTask.objects.filter(property=selected).select_related("unit", "assigned_to") if selected else HousekeepingTask.objects.none()
    status = request.GET.get("status")
    if status in HousekeepingStatus.values:
        tasks_qs = tasks_qs.filter(status=status)
    floor = request.GET.get("floor", "").strip()
    if floor:
        tasks_qs = tasks_qs.filter(unit__floor=floor)
    floors = selected.units.exclude(floor="").values_list("floor", flat=True).distinct().order_by("floor") if selected else []
    history = HousekeepingTaskHistory.objects.filter(property=selected).select_related("unit", "assigned_to", "changed_by")[:80] if selected else HousekeepingTaskHistory.objects.none()
    return render(request, "booking/operations/housekeeping.html", {
        "title": "Housekeeping",
        "properties": properties, "selected_property": selected, "tasks": tasks_qs,
        "units": selected.units.select_related("unit_type") if selected else Unit.objects.none(),
        "users": _users_for_property(selected), "status_choices": HousekeepingStatus.choices,
        "priority_choices": TaskPriority.choices, "floors": floors, "selected_floor": floor, "now": timezone.now(),
        "history": history,
    })


@login_required
def maintenance(request):
    properties, selected = _selected_property(request)
    if _permission_denied(request, selected, "operations.maintenance.manage"):
        return HttpResponseForbidden("Bu tesis için teknik servis erişiminiz yok.")
    if request.method == "POST" and selected:
        action = request.POST.get("action")
        ticket = MaintenanceTicket.objects.filter(property=selected, id=request.POST.get("ticket_id")).first()
        if action == "create" and request.POST.get("title"):
            sla_due_at = parse_datetime(request.POST.get("sla_due_at", ""))
            if sla_due_at and timezone.is_naive(sla_due_at):
                sla_due_at = timezone.make_aware(sla_due_at)
            new_ticket = MaintenanceTicket.objects.create(
                property=selected,
                unit=selected.units.filter(id=request.POST.get("unit_id")).first(),
                title=request.POST["title"], description=request.POST.get("description", ""),
                priority=request.POST.get("priority", TaskPriority.NORMAL),
                assigned_to_id=request.POST.get("assigned_to") or None, created_by=request.user,
                sla_due_at=sla_due_at,
                estimated_cost=request.POST.get("estimated_cost") or None,
            )
            MaintenanceTicketHistory.objects.create(
                ticket=new_ticket, property=selected, status=new_ticket.status,
                assigned_to=new_ticket.assigned_to, resolution_note=new_ticket.resolution_note,
                estimated_cost=new_ticket.estimated_cost, actual_cost=new_ticket.actual_cost,
                changed_by=request.user,
            )
        elif ticket and action == "status" and request.POST.get("status") in MaintenanceStatus.values:
            ticket.status = request.POST["status"]
            ticket.assigned_to_id = request.POST.get("assigned_to") or None
            ticket.resolution_note = request.POST.get("resolution_note", "").strip()
            ticket.actual_cost = request.POST.get("actual_cost") or None
            if ticket.status == MaintenanceStatus.RESOLVED:
                ticket.resolved_at = timezone.now()
                ticket.resolved_by = request.user
            else:
                ticket.resolved_at = None
                ticket.resolved_by = None
            ticket.save(update_fields=["status", "assigned_to", "resolution_note", "actual_cost", "resolved_at", "resolved_by", "updated_at"])
            MaintenanceTicketHistory.objects.create(
                ticket=ticket, property=selected, status=ticket.status,
                assigned_to=ticket.assigned_to, resolution_note=ticket.resolution_note,
                estimated_cost=ticket.estimated_cost, actual_cost=ticket.actual_cost,
                changed_by=request.user,
            )
        return redirect(f"{reverse('operations:maintenance')}?property_id={selected.id}")
    tickets = MaintenanceTicket.objects.filter(property=selected).select_related("unit", "assigned_to") if selected else MaintenanceTicket.objects.none()
    floor = request.GET.get("floor", "").strip()
    if floor:
        tickets = tickets.filter(unit__floor=floor)
    floors = selected.units.exclude(floor="").values_list("floor", flat=True).distinct().order_by("floor") if selected else []
    history = MaintenanceTicketHistory.objects.filter(property=selected).select_related("ticket", "assigned_to", "changed_by")[:80] if selected else MaintenanceTicketHistory.objects.none()
    return render(request, "booking/operations/maintenance.html", {
        "title": "Teknik Servis",
        "properties": properties, "selected_property": selected, "tickets": tickets,
        "units": selected.units.all() if selected else Unit.objects.none(), "users": _users_for_property(selected),
        "status_choices": MaintenanceStatus.choices, "priority_choices": TaskPriority.choices,
        "now": timezone.now(), "floors": floors, "selected_floor": floor,
        "history": history,
    })


@login_required
def tasks(request):
    properties, selected = _selected_property(request)
    if _permission_denied(request, selected, "operations.tasks.manage"):
        return HttpResponseForbidden("Bu tesis için görev yönetimi erişiminiz yok.")
    task = OperationalTask.objects.filter(property=selected, id=request.POST.get("task_id")).first() if selected else None
    if request.method == "POST" and selected:
        action = request.POST.get("action")
        if action == "create":
            form = OperationalTaskForm(request.POST)
            _task_form_querysets(form, selected)
            if form.is_valid():
                obj = form.save(commit=False); obj.property = selected; obj.source = "manual"; obj.save()
                messages.success(request, "Görev oluşturuldu.")
        elif task and action == "update":
            form = OperationalTaskForm(request.POST, instance=task)
            _task_form_querysets(form, selected)
            if form.is_valid():
                obj = form.save(commit=False)
                if obj.status == TaskStatus.DONE and not obj.completed_at:
                    obj.completed_at = timezone.now()
                    obj.completed_by = request.user
                elif obj.status != TaskStatus.DONE:
                    obj.completed_at = None
                    obj.completed_by = None
                obj.save(); messages.success(request, "Görev güncellendi.")
        elif action in {"group", "location"}:
            model = TaskGroup if action == "group" else TaskLocation
            if request.POST.get("code") and request.POST.get("name"):
                model.objects.create(property=selected, code=request.POST["code"], name=request.POST["name"])
                messages.success(request, "Görev sözlüğü kaydedildi.")
        return redirect(f"{reverse('operations:tasks')}?property_id={selected.id}")
    form = OperationalTaskForm()
    if selected: _task_form_querysets(form, selected)
    tasks_qs = OperationalTask.objects.filter(property=selected).select_related("group", "location", "unit", "assigned_to") if selected else OperationalTask.objects.none()
    floor = request.GET.get("floor", "").strip()
    if floor:
        tasks_qs = tasks_qs.filter(unit__floor=floor)
    floors = selected.units.exclude(floor="").values_list("floor", flat=True).distinct().order_by("floor") if selected else []
    return render(request, "booking/operations/tasks.html", {
        "title": "Görev Yönetimi",
        "properties": properties, "selected_property": selected, "tasks": tasks_qs,
        "form": form, "task_groups": TaskGroup.objects.filter(property=selected) if selected else TaskGroup.objects.none(),
        "task_locations": TaskLocation.objects.filter(property=selected) if selected else TaskLocation.objects.none(),
        "status_choices": TaskStatus.choices, "priority_choices": TaskPriority.choices,
        "now": timezone.now(), "floors": floors, "selected_floor": floor,
    })


def _task_form_querysets(form, property_):
    form.fields["group"].queryset = TaskGroup.objects.filter(property=property_, is_active=True)
    form.fields["location"].queryset = TaskLocation.objects.filter(property=property_, is_active=True)
    form.fields["unit"].queryset = property_.units.filter(is_active=True)
    user_ids = Membership.objects.filter(
        Q(organization=property_.organization, property__isnull=True) | Q(property=property_), is_active=True,
    ).values_list("user_id", flat=True)
    form.fields["assigned_to"].queryset = get_user_model().objects.filter(id__in=user_ids)


@login_required
def online_settings(request):
    properties, selected = _selected_property(request)
    if _permission_denied(request, selected, "operations.online_settings.manage"):
        return HttpResponseForbidden("Bu tesis için online booking ayarlarına erişiminiz yok.")
    settings_obj = OnlineBookingSettings.objects.get_or_create(property=selected)[0] if selected else None
    photo_form = HotelPhotoForm()
    if request.method == "POST" and settings_obj and request.POST.get("action") == "photo":
        photo_form = HotelPhotoForm(request.POST, request.FILES)
        if photo_form.is_valid():
            photo = photo_form.save(commit=False)
            photo.property = selected
            photo.save()
            messages.success(request, "Online görsel kaydedildi.")
        return redirect(f"{reverse('operations:online_settings')}?property_id={selected.id}")
    if request.method == "POST" and settings_obj and request.POST.get("action") == "service":
        service_form = PropertyServiceForm(request.POST)
        if service_form.is_valid():
            service = service_form.save(commit=False)
            service.property = selected
            service.save()
            messages.success(request, "Online hizmet kaydedildi.")
        return redirect(f"{reverse('operations:online_settings')}?property_id={selected.id}")
    if request.method == "POST" and settings_obj and request.POST.get("action") == "service_request_status":
        service_request = ServiceRequest.objects.filter(
            id=request.POST.get("request_id"), reservation__property=selected,
        ).first()
        if service_request and request.POST.get("status") in ServiceRequest.Status.values:
            service_request.status = request.POST["status"]
            service_request.save(update_fields=["status", "updated_at"])
            messages.success(request, "Hizmet talebi güncellendi.")
        return redirect(f"{reverse('operations:online_settings')}?property_id={selected.id}")
    if request.method == "POST" and settings_obj:
        selected_provider = request.POST.get("payment_provider", settings_obj.payment_provider)
        payment_active = request.POST.get("online_payment_active") == "on"
        provider_ready = {
            OnlineBookingSettings.PaymentProvider.STRIPE: bool(django_settings.PAYMENT_STRIPE_SECRET_KEY),
            OnlineBookingSettings.PaymentProvider.PAYPAL: bool(
                django_settings.PAYMENT_PAYPAL_CLIENT_ID and django_settings.PAYMENT_PAYPAL_CLIENT_SECRET
            ),
        }
        if payment_active and selected_provider == OnlineBookingSettings.PaymentProvider.MANUAL:
            messages.error(request, "Online ödeme için Stripe veya PayPal seçilmelidir.")
            return redirect(f"{reverse('operations:online_settings')}?property_id={selected.id}")
        if payment_active and selected_provider in provider_ready and not provider_ready[selected_provider]:
            messages.error(request, "Seçilen ödeme sağlayıcısının production anahtarları yapılandırılmamış.")
            return redirect(f"{reverse('operations:online_settings')}?property_id={selected.id}")
        for field in [f.name for f in OnlineBookingSettings._meta.fields if isinstance(f, BooleanField)]:
            setattr(settings_obj, field, request.POST.get(field) == "on")
        for field in ["seo_title", "seo_description", "meta_keywords", "canonical_url", "og_title", "og_image_url", "google_analytics_id", "google_tag_manager_id", "google_maps_cid", "domain", "facebook_url", "instagram_url", "whatsapp_url", "google_business_url", "payment_provider", "payment_public_key"]:
            setattr(settings_obj, field, request.POST.get(field, "").strip())
        try:
            settings_obj.deposit_percent = max(0, min(100, float(request.POST.get("deposit_percent") or 0)))
            settings_obj.payment_due_hours = max(0, int(request.POST.get("payment_due_hours") or 24))
        except ValueError:
            messages.error(request, "Ödeme yüzdesi veya ödeme vadesi geçersiz.")
        settings_obj.save()
        messages.success(request, "Online booking ayarları kaydedildi.")
        return redirect(f"{reverse('operations:online_settings')}?property_id={selected.id}")
    return render(request, "booking/operations/online_settings.html", {
        "title": "Online Booking Ayarları",
        "properties": properties, "selected_property": selected, "settings": settings_obj,
        "service_form": PropertyServiceForm(),
        "services": selected.online_services.all() if selected else PropertyService.objects.none(),
        "service_requests": ServiceRequest.objects.filter(reservation__property=selected).select_related("reservation", "reservation__guest", "service")[:50] if selected else ServiceRequest.objects.none(),
        "photo_form": photo_form,
        "photos": HotelPhoto.objects.filter(property=selected) if selected else HotelPhoto.objects.none(),
        "service_status_choices": ServiceRequest.Status.choices,
        "payment_provider_choices": OnlineBookingSettings.PaymentProvider.choices,
    })


@login_required
def crm_guests(request):
    properties, selected = _selected_property(request)
    if _permission_denied(request, selected, "operations.crm.guests.view"):
        return HttpResponseForbidden("Bu tesis için CRM erişiminiz yok.")
    guests = Guest.objects.filter(property=selected).select_related("profile_extension", "loyalty_account") if selected else Guest.objects.none()
    q = request.GET.get("q", "").strip()
    if q:
        guests = guests.filter(Q(first_name__icontains=q) | Q(last_name__icontains=q) | Q(email__icontains=q) | Q(phone__icontains=q))
    selected_guest = guests.filter(id=request.GET.get("guest_id")).first() if selected and request.GET.get("guest_id") else None
    profile = GuestProfileExtension.objects.filter(guest=selected_guest).first() if selected_guest else None
    if selected_guest and not profile:
        profile = GuestProfileExtension(guest=selected_guest)
    profile_form = GuestProfileForm(request.POST or None, instance=profile) if selected_guest else None
    tier_form = LoyaltyTierForm(request.POST or None) if selected else None
    if request.method == "POST" and selected:
        action = request.POST.get("action")
        if action == "profile" and selected_guest and profile_form and profile_form.is_valid():
            profile_form.save(); messages.success(request, "Misafir profili kaydedildi.")
        elif action == "tier" and tier_form and tier_form.is_valid():
            obj = tier_form.save(commit=False); obj.property = selected; obj.save(); messages.success(request, "Sadakat seviyesi kaydedildi.")
        elif action == "loyalty" and selected_guest and request.POST.get("membership_number"):
            tier = selected.loyalty_tiers.filter(id=request.POST.get("tier_id"), is_active=True).first()
            GuestLoyaltyAccount.objects.update_or_create(guest=selected_guest, defaults={"property": selected, "tier": tier, "membership_number": request.POST["membership_number"], "points_balance": request.POST.get("points_balance") or 0})
            messages.success(request, "Sadakat hesabı kaydedildi.")
        elif action == "loyalty_tx" and selected_guest:
            account = GuestLoyaltyAccount.objects.filter(guest=selected_guest, property=selected).first()
            try:
                amount = abs(int(request.POST.get("points") or 0))
            except ValueError:
                amount = 0
            kind = request.POST.get("kind")
            if account and amount and kind in {"earn", "redeem", "adjust"}:
                delta = amount if kind == "earn" else -amount if kind == "redeem" else int(request.POST.get("signed_points") or 0)
                if delta < 0 and account.points_balance + delta < 0:
                    messages.error(request, "Puan bakiyesi eksiye düşemez.")
                else:
                    LoyaltyTransaction.objects.create(account=account, kind=kind, points=delta, note=request.POST.get("note", ""), created_by=request.user)
                    account.points_balance += delta
                    account.tier = account.property.loyalty_tiers.filter(
                        is_active=True, minimum_points__lte=account.points_balance,
                    ).order_by("-minimum_points").first()
                    account.save(update_fields=["points_balance", "tier", "updated_at"])
                    messages.success(request, "Sadakat puan hareketi kaydedildi.")
        return redirect(f"{reverse('operations:crm_guests')}?property_id={selected.id}&q={q}&guest_id={selected_guest.id if selected_guest else ''}")
    return render(request, "booking/operations/crm_guests.html", {
        "title": "Misafir CRM",
        "properties": properties, "selected_property": selected, "guests": guests, "query": q,
        "selected_guest": selected_guest, "profile_form": profile_form, "tier_form": tier_form,
        "tiers": selected.loyalty_tiers.filter(is_active=True) if selected else LoyaltyTier.objects.none(),
        "loyalty": getattr(selected_guest, "loyalty_account", None) if selected_guest else None,
    })


@login_required
def crm_marketing(request):
    properties, selected = _selected_property(request)
    if _permission_denied(request, selected, "operations.crm.marketing.manage"):
        return HttpResponseForbidden("Bu tesis için CRM pazarlama erişiminiz yok.")
    entity = request.POST.get("entity") or request.GET.get("entity", "segment")
    forms = {
        "segment": GuestSegmentForm(request.POST or None),
        "template": MessageTemplateForm(request.POST or None),
        "campaign": MarketingCampaignForm(request.POST or None),
    }
    if entity not in forms:
        entity = "segment"
    form = forms[entity]
    if selected and entity == "campaign":
        form.fields["segment"].queryset = selected.guest_segments.filter(is_active=True)
        form.fields["template"].queryset = selected.message_templates.filter(is_active=True)
    if request.method == "POST" and selected and request.POST.get("action") == "prepare_campaign":
        campaign = selected.marketing_campaigns.filter(id=request.POST.get("campaign_id")).select_related("segment", "template").first()
        if campaign and campaign.segment and campaign.template:
            criteria = campaign.segment.criteria or {}
            guests = Guest.objects.filter(property=selected)
            if criteria.get("vip_only"):
                guests = guests.filter(profile_extension__vip=True)
            if criteria.get("gdpr_required"):
                guests = guests.filter(profile_extension__gdpr_confirmed=True)
            if criteria.get("country"):
                guests = guests.filter(country__iexact=criteria["country"])
            if criteria.get("has_email") and campaign.template.channel == MessageTemplate.Channel.EMAIL:
                guests = guests.exclude(email="")
            created = 0
            for guest in guests.iterator():
                recipient = guest.email if campaign.template.channel == MessageTemplate.Channel.EMAIL else guest.phone
                if not recipient:
                    continue
                _, was_created = MarketingDelivery.objects.get_or_create(
                    campaign=campaign, guest=guest,
                    defaults={"channel": campaign.template.channel, "recipient": recipient},
                )
                created += int(was_created)
            campaign.status = MarketingCampaign.Status.SCHEDULED
            campaign.save(update_fields=["status"])
            messages.success(request, f"{created} alıcı kampanya kuyruğuna alındı.")
        return redirect(f"{reverse('operations:crm_marketing')}?property_id={selected.id}&entity=campaign")
    if request.method == "POST" and selected and form.is_valid():
        obj = form.save(commit=False)
        obj.property = selected
        if hasattr(obj, "created_by"):
            obj.created_by = request.user
        obj.save()
        return redirect(f"{reverse('operations:crm_marketing')}?property_id={selected.id}&entity={entity}")
    return render(request, "booking/operations/crm_marketing.html", {
        "title": "CRM Kampanya ve Şablonlar", "properties": properties, "selected_property": selected,
        "entity": entity, "form": form,
        "segments": selected.guest_segments.all() if selected else GuestSegment.objects.none(),
        "templates": selected.message_templates.all() if selected else MessageTemplate.objects.none(),
        "campaigns": selected.marketing_campaigns.select_related("segment", "template") if selected else MarketingCampaign.objects.none(),
    })


@login_required
def access_control(request):
    properties, selected = _selected_property(request)
    if _permission_denied(request, selected, "operations.access.manage"):
        return HttpResponseForbidden("Bu tesis için yetki yönetimi erişiminiz yok.")
    role_form = PropertyRoleForm(request.POST or None, prefix="role")
    access_form = UserPropertyAccessForm(request.POST or None, prefix="access")
    pin_form = UserPinChangeForm(request.POST or None, prefix="pin")
    staff_users = get_user_model().objects.none()
    if selected:
        role_form.fields["permissions"].queryset = AccessPermission.objects.filter(is_active=True)
        access_form.fields["role"].queryset = selected.access_roles.filter(is_active=True)
        staff_users = get_user_model().objects.filter(
            id__in=Membership.objects.filter(
                Q(organization=selected.organization, property__isnull=True) | Q(property=selected), is_active=True,
            ).values_list("user_id", flat=True),
        ).order_by("username")
        access_form.fields["user"].queryset = staff_users
    user_status = request.GET.get("user_status", "active")
    if user_status not in {"active", "passive", "all"}:
        user_status = "active"
    if user_status == "active":
        staff_users = staff_users.filter(is_active=True)
    elif user_status == "passive":
        staff_users = staff_users.filter(is_active=False)
    department_filter = request.GET.get("department", "")
    if department_filter:
        staff_users = staff_users.filter(department=department_filter)
    profile_user_id = request.POST.get("profile_user_id") or request.GET.get("profile_user_id")
    profile_user = staff_users.filter(id=profile_user_id).first() if profile_user_id else None
    profile_form = UserProfileForm(request.POST or None, instance=profile_user, prefix="profile")
    if request.method == "POST" and selected:
        action = request.POST.get("action")
        if action == "mfa_reset":
            if not _can_manage_user_mfa(request, selected):
                return HttpResponseForbidden("Bu tesis için başka kullanıcıların 2FA ayarlarını yönetme yetkiniz yok.")
            target_user = staff_users.filter(id=request.POST.get("mfa_user_id")).first()
            if target_user:
                Authenticator.objects.filter(user=target_user).delete()
                UserAccessLog.objects.create(actor=request.user, user=target_user, property=selected, event="mfa_reset_by_admin", metadata={"target_user_id": target_user.id, "action": "reset_authenticators"})
                messages.success(request, "Kullanıcının 2FA kurulumu ve recovery code'ları sıfırlandı.")
            return redirect(f"{reverse('operations:access_control')}?property_id={selected.id}&profile_user_id={target_user.id if target_user else ''}")
        if action == "pin" and pin_form.is_valid():
            target_user = staff_users.filter(id=request.POST.get("pin_user_id")).first()
            if target_user:
                access = UserPropertyAccess.objects.filter(user=target_user, property=selected, is_active=True).order_by("id").first()
                if access:
                    access.pin_hash = make_password(pin_form.cleaned_data["pin"])
                    access.last_pin_change = timezone.now()
                    access.save(update_fields=["pin_hash", "last_pin_change"])
                    UserAccessLog.objects.create(actor=request.user, user=target_user, property=selected, event="pin_changed", metadata={"target_user_id": target_user.id, "action": "replace_pin"})
                    messages.success(request, "Kullanıcı PIN'i güncellendi.")
                else:
                    messages.error(request, "Bu kullanıcının seçili tesiste aktif erişimi bulunmuyor.")
            return redirect(f"{reverse('operations:access_control')}?property_id={selected.id}&profile_user_id={target_user.id if target_user else ''}")
        if action == "role" and role_form.is_valid():
            role = role_form.save(commit=False)
            role.property = selected
            role.save()
            role_form.save_m2m()
            UserAccessLog.objects.create(actor=request.user, property=selected, event="role_created", metadata={"role_id": role.id, "role": role.name, "department": role.department, "permission_codes": list(role.permissions.values_list("code", flat=True))})
            messages.success(request, "Property rolü kaydedildi.")
            return redirect(f"{reverse('operations:access_control')}?property_id={selected.id}")
        if action == "profile" and profile_user and profile_form.is_valid():
            profile_form.save()
            UserAccessLog.objects.create(actor=request.user, user=profile_user, property=selected, event="user_profile_updated", metadata={"target_user_id": profile_user.id, "changed_fields": profile_form.changed_data})
            messages.success(request, "Kullanıcı profili kaydedildi.")
            return redirect(f"{reverse('operations:access_control')}?property_id={selected.id}&profile_user_id={profile_user.id}")
        if action == "access" and access_form.is_valid():
            access = access_form.save(commit=False)
            access.property = selected
            pin = access_form.cleaned_data.get("pin")
            if pin:
                access.pin_hash = make_password(pin)
                access.last_pin_change = timezone.now()
            access.save()
            UserAccessLog.objects.create(actor=request.user, user=access.user, property=selected, event="property_access_assigned", metadata={"target_user_id": access.user_id, "role_id": access.role_id, "role": access.role.name, "department": access.role.department, "financial_access": access.financial_access, "two_factor_required": access.two_factor_required})
            messages.success(request, "Kullanıcı property erişimi kaydedildi.")
            return redirect(f"{reverse('operations:access_control')}?property_id={selected.id}")
    memberships = Membership.objects.filter(
        organization=selected.organization if selected else None,
        property__isnull=True,
        is_active=True,
    ).select_related("user") if selected else Membership.objects.none()
    property_memberships = Membership.objects.filter(
        property=selected, is_active=True,
    ).select_related("user") if selected else Membership.objects.none()
    mfa_totp = Authenticator.objects.filter(user=profile_user, type=Authenticator.Type.TOTP).first() if profile_user else None
    mfa_recovery = Authenticator.objects.filter(user=profile_user, type=Authenticator.Type.RECOVERY_CODES).first() if profile_user else None
    mfa_unused_count = len(mfa_recovery.wrap().get_unused_codes()) if mfa_recovery else 0
    profile_user_access = UserPropertyAccess.objects.filter(user=profile_user, property=selected, is_active=True).order_by("id").first() if profile_user and selected else None
    profile_user_accesses = UserPropertyAccess.objects.filter(
        user=profile_user, property=selected, is_active=True,
    ).select_related("role").prefetch_related("role__permissions") if profile_user and selected else UserPropertyAccess.objects.none()
    accesses = selected.user_accesses.select_related("user", "role") if selected else UserPropertyAccess.objects.none()
    if department_filter:
        accesses = accesses.filter(Q(user__department=department_filter) | Q(role__department=department_filter))
    return render(request, "booking/operations/access_control.html", {
        "title": "Kullanıcı ve Yetki",
        "properties": properties, "selected_property": selected,
        "memberships": list(memberships) + list(property_memberships),
        "user_status": user_status, "department_filter": department_filter, "department_choices": DEPARTMENT_CHOICES,
        "roles": selected.access_roles.prefetch_related("permissions") if selected else PropertyRole.objects.none(),
        "permission_catalog": AccessPermission.objects.filter(is_active=True) if selected else AccessPermission.objects.none(),
        "accesses": accesses,
        "logs": selected.access_logs.select_related("user").all()[:25] if selected else UserAccessLog.objects.none(),
        "role_form": role_form, "access_form": access_form, "pin_form": pin_form, "staff_users": staff_users,
        "profile_user": profile_user, "profile_form": profile_form,
        "profile_user_access": profile_user_access,
        "profile_user_accesses": profile_user_accesses,
        "mfa_enabled": bool(profile_user and is_mfa_enabled(profile_user)),
        "mfa_totp": mfa_totp, "mfa_recovery": mfa_recovery, "mfa_unused_count": mfa_unused_count,
        "can_manage_user_mfa": _can_manage_user_mfa(request, selected),
    })


@login_required
def property_settings(request):
    properties, selected = _selected_property(request)
    if _permission_denied(request, selected, "operations.property.settings.manage"):
        return HttpResponseForbidden("Bu tesis için property settings erişiminiz yok.")
    settings_obj = PropertySettings.objects.filter(property=selected).first() if selected else None
    form = PropertySettingsForm(request.POST or None, instance=settings_obj)
    property_form = PropertyProfileForm(request.POST or None, instance=selected) if selected else PropertyProfileForm()
    if request.method == "POST" and selected:
        if request.POST.get("form_type") == "profile" and property_form.is_valid():
            property_form.save()
            messages.success(request, "Tesis bilgileri kaydedildi.")
        elif request.POST.get("form_type") != "profile" and form.is_valid():
            obj = form.save(commit=False)
            obj.property = selected
            obj.save()
            messages.success(request, "Otel ayarları kaydedildi.")
        return redirect(f"{reverse('operations:property_settings')}?property_id={selected.id}")
    return render(request, "booking/operations/property_settings.html", {
        "title": "Property Settings", "property_form": property_form,
        "properties": properties, "selected_property": selected, "form": form,
    })


@login_required
def hotel_dictionaries(request):
    properties, selected = _selected_property(request)
    if _permission_denied(request, selected, "operations.hotel.dictionaries.manage"):
        return HttpResponseForbidden("Bu tesis için sözlük yönetimi erişiminiz yok.")
    form_map = {
        "room_group": (RoomGroup, RoomGroupForm), "bed_type": (BedType, BedTypeForm),
        "room_view": (RoomView, RoomViewForm), "room_location": (RoomLocation, RoomLocationForm),
        "room_photo": (RoomPhoto, RoomPhotoForm), "hotel_photo": (HotelPhoto, HotelPhotoForm),
        "board_type": (BoardType, BoardTypeForm), "rate_type": (RateType, RateTypeForm),
    }
    active = request.POST.get("entity") or request.GET.get("entity", "board_type")
    if active not in form_map:
        active = "board_type"
    model, form_class = form_map[active]
    edit_id = request.POST.get("edit_id") or request.GET.get("edit_id")
    instance = model.objects.filter(property=selected, id=edit_id).first() if selected and edit_id else None
    form = form_class(request.POST or None, request.FILES or None, instance=instance)
    if selected and active == "room_photo":
        form.fields["unit_type"].queryset = selected.unit_types.filter(is_active=True)
        form.fields["unit"].queryset = selected.units.filter(is_active=True)
    if request.method == "POST" and selected and request.POST.get("action") == "delete":
        model.objects.filter(property=selected, id=request.POST.get("item_id")).delete()
        return redirect(f"{reverse('operations:hotel_dictionaries')}?property_id={selected.id}&entity={active}")
    if request.method == "POST" and selected and form.is_valid():
        obj = form.save(commit=False)
        obj.property = selected
        obj.save()
        messages.success(request, "Tanım kaydedildi.")
        return redirect(f"{reverse('operations:hotel_dictionaries')}?property_id={selected.id}&entity={active}")
    lists = {key: model.objects.filter(property=selected) if selected else model.objects.none() for key, (model, _) in form_map.items()}
    return render(request, "booking/operations/hotel_dictionaries.html", {
        "title": "Hotel Dictionaries",
        "properties": properties, "selected_property": selected, "active_entity": active,
        "form": form, "lists": lists, "selected_items": lists[active],
        "entity_labels": {"room_group": "Oda grubu", "bed_type": "Yatak tipi", "room_view": "Manzara", "room_location": "Konum", "room_photo": "Oda fotoğrafı", "hotel_photo": "Otel fotoğrafı", "board_type": "Board Type", "rate_type": "Rate Type"},
    })


@login_required
def room_master(request):
    properties, selected = _selected_property(request)
    if _permission_denied(request, selected, "operations.room.master.manage"):
        return HttpResponseForbidden("Bu tesis için room master erişiminiz yok.")
    entity = request.POST.get("entity") or request.GET.get("entity", "unit_type")
    if entity not in {"unit_type", "unit"}:
        entity = "unit_type"
    edit_id = request.POST.get("edit_id") or request.GET.get("edit_id")
    model = UnitType if entity == "unit_type" else Unit
    instance = model.objects.filter(property=selected, id=edit_id).first() if selected and edit_id else None
    form = UnitTypeForm(request.POST or None, instance=instance) if entity == "unit_type" else UnitForm(request.POST or None, instance=instance)
    if entity == "unit_type":
        form.fields["room_group"].queryset = RoomGroup.objects.filter(property=selected, is_active=True) if selected else RoomGroup.objects.none()
        form.fields["amenities"].queryset = selected.roomamenity_set.filter(is_active=True) if selected else form.fields["amenities"].queryset.none()
    else:
        form.fields["unit_type"].queryset = selected.unit_types.filter(is_active=True) if selected else UnitType.objects.none()
        form.fields["bed_type"].queryset = BedType.objects.filter(property=selected, is_active=True) if selected else BedType.objects.none()
        form.fields["room_view"].queryset = RoomView.objects.filter(property=selected, is_active=True) if selected else RoomView.objects.none()
        form.fields["room_location"].queryset = RoomLocation.objects.filter(property=selected, is_active=True) if selected else RoomLocation.objects.none()
    if request.method == "POST" and selected:
        action = request.POST.get("action", "save")
        if action == "delete":
            if entity == "unit_type":
                UnitType.objects.filter(property=selected, id=request.POST.get("item_id")).delete()
            else:
                Unit.objects.filter(property=selected, id=request.POST.get("item_id")).delete()
            return redirect(f"{reverse('operations:room_master')}?property_id={selected.id}&entity={entity}")
        if form.is_valid():
            obj = form.save(commit=False)
            obj.property = selected
            obj.save()
            form.save_m2m()
            return redirect(f"{reverse('operations:room_master')}?property_id={selected.id}&entity={entity}")
    return render(request, "booking/operations/room_master.html", {
        "title": "Room Master", "properties": properties, "selected_property": selected,
        "entity": entity, "form": form,
        "unit_types": selected.unit_types.select_related("room_group") if selected else UnitType.objects.none(),
        "units": selected.units.select_related("unit_type", "bed_type", "room_view", "room_location") if selected else Unit.objects.none(),
    })


@login_required
def room_rack(request):
    properties, selected = _selected_property(request)
    if _permission_denied(request, selected, "operations.front.office.manage"):
        return HttpResponseForbidden("Bu tesis için front office erişiminiz yok.")
    selected_date = parse_date(request.POST.get("rack_date") or request.GET.get("rack_date", "")) or timezone.localdate()
    if request.method == "POST" and selected:
        item = ReservationItem.objects.filter(
            id=request.POST.get("item_id"), reservation__property=selected,
        ).select_related("reservation", "unit").first()
        action = request.POST.get("action")
        try:
            if item and action == "check_in":
                item.check_in(actor=request.user)
                messages.success(request, f"{item.reservation.reference} için check-in tamamlandı.")
            elif item and action == "check_out":
                item.check_out(actor=request.user)
                if item.unit_id:
                    UnitHousekeepingState.objects.update_or_create(
                        unit=item.unit,
                        defaults={"status": HousekeepingStatus.DIRTY, "note": "Check-out sonrası temizlik bekliyor.", "changed_by": request.user},
                    )
                    HousekeepingTask.objects.get_or_create(
                        property=selected,
                        unit=item.unit,
                        status=HousekeepingStatus.DIRTY,
                        defaults={
                            "priority": TaskPriority.NORMAL,
                            "note": "Otomatik check-out temizliği",
                        },
                    )
                messages.success(request, f"{item.reservation.reference} için check-out tamamlandı.")
            elif item and action == "move_unit":
                target = selected.units.filter(id=request.POST.get("unit_id"), is_active=True).first()
                if not target:
                    raise ValidationError("Geçerli bir oda seçilmedi.")
                if target.unit_type_id != item.unit_type_id:
                    raise ValidationError("Oda tipi rezervasyonun oda tipiyle aynı olmalıdır.")
                if target.status in {"maintenance", "out_of_service"} or target.is_locked:
                    raise ValidationError("Seçilen oda bakımda, kullanım dışı veya kilitli.")
                conflict = ReservationItem.objects.filter(
                    reservation__property=selected, unit=target,
                    reservation__status__in=[ReservationStatus.PENDING, ReservationStatus.CONFIRMED],
                    reservation__check_in__lt=item.reservation.check_out,
                    reservation__check_out__gt=item.reservation.check_in,
                ).exclude(id=item.id).exists()
                if conflict:
                    raise ValidationError("Seçilen oda rezervasyon tarihleri içinde dolu.")
                item.unit = target
                item.save(update_fields=["unit", "updated_at"])
                messages.success(request, f"{item.reservation.reference} oda {target.code} olarak güncellendi.")
        except ValidationError as exc:
            messages.error(request, str(exc))
        return redirect(f"{reverse('operations:room_rack')}?property_id={selected.id}&rack_date={selected_date.isoformat()}")

    occupied = ReservationItem.objects.filter(
        reservation__property=selected,
        reservation__status__in=[ReservationStatus.PENDING, ReservationStatus.CONFIRMED],
        reservation__check_in__lte=selected_date,
        reservation__check_out__gt=selected_date,
        unit__isnull=False,
    ).select_related("reservation", "reservation__guest", "unit", "unit_type") if selected else ReservationItem.objects.none()
    by_unit = {item.unit_id: item for item in occupied}
    rooms = []
    if selected:
        states = {state.unit_id: state for state in UnitHousekeepingState.objects.filter(unit__property=selected)}
        units_by_type = {}
        for candidate in selected.units.filter(is_active=True).order_by("floor", "code"):
            units_by_type.setdefault(candidate.unit_type_id, []).append(candidate)
        for unit in selected.units.select_related("unit_type", "unit_type__room_group").order_by("floor", "code"):
            item = by_unit.get(unit.id)
            housekeeping_state = states.get(unit.id)
            if unit.status == "maintenance":
                rack_status = "Bakım"
            elif unit.status == "out_of_service":
                rack_status = "Kullanım dışı"
            elif item and item.stay_status == StayStatus.CHECKED_IN:
                rack_status = "Konaklıyor"
            elif item:
                rack_status = "Giriş bekliyor"
            elif housekeeping_state and housekeeping_state.status != HousekeepingStatus.CLEAN:
                rack_status = housekeeping_state.get_status_display()
            else:
                rack_status = "Müsait"
            rooms.append({"unit": unit, "item": item, "status": rack_status, "available_units": units_by_type.get(unit.unit_type_id, [])})
    unassigned = ReservationItem.objects.filter(
        reservation__property=selected, unit__isnull=True,
        reservation__status__in=[ReservationStatus.PENDING, ReservationStatus.CONFIRMED],
        reservation__check_in__lte=selected_date, reservation__check_out__gt=selected_date,
    ).select_related("reservation", "reservation__guest", "unit_type") if selected else ReservationItem.objects.none()
    unassigned = list(unassigned)
    for item in unassigned:
        item.rack_units = units_by_type.get(item.unit_type_id, []) if selected else []
    return render(request, "booking/operations/room_rack.html", {
        "title": "Room Rack",
        "properties": properties, "selected_property": selected, "rack_date": selected_date,
        "rooms": rooms, "unassigned": unassigned, "units_by_type": units_by_type if selected else {},
    })

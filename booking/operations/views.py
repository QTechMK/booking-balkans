from datetime import timedelta

from django.conf import settings as django_settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.core.exceptions import ValidationError
from django.db.models import Q, Sum
from django.db.models import BooleanField
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from allauth.mfa.models import Authenticator
from allauth.mfa.utils import is_mfa_enabled

from booking.reservations.models import Guest, Reservation, ReservationItem, ReservationStatus, StayStatus
from booking.reservations.views import _business_properties
from booking.tenancy.models import (
    BedType, BoardType, Membership, Property, PropertySettings, RateType,
    RoomGroup, RoomLocation, RoomPhoto, RoomView, Unit, UnitType,
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
    AccessPermission, GuestLoyaltyAccount, GuestProfileExtension, GuestSegment, LoyaltyTier, LoyaltyTransaction, MarketingCampaign, MarketingDelivery, MessageTemplate, OperationalTask, PropertyService, ServiceRequest,
    PropertyRole,
    TaskPriority,
    TaskGroup,
    TaskLocation,
    TaskStatus, UserAccessLog, UserPropertyAccess, Agency, DepartmentDefinition, FrontOfficeCallRequest, Invoice, NightAuditRun, PaymentGateway, RevenueCode, SupportAuditEvent, SupportEducationRequest, SupportFAQCategory, SupportFAQItem, SupportHelpLink, SupportReferral, SupportTicket, SupportTicketMessage, SupportVideoCategory,
    UnitHousekeepingState,
)
from .forms import (
    BedTypeForm, BoardTypeForm, DEPARTMENT_CHOICES, PropertyProfileForm, PropertySettingsForm, RateTypeForm,
    AgencyForm, DepartmentDefinitionForm, FrontOfficeCallRequestForm, GuestProfileForm, GuestSegmentForm, InvoiceForm, LoyaltyTierForm, MarketingCampaignForm, MessageTemplateForm, OperationalTaskForm, PaymentGatewayForm, PropertyRoleForm, PropertyServiceForm, RevenueCodeForm, RoomGroupForm, RoomLocationForm, RoomPhotoForm, RoomViewForm, SupportEducationRequestForm, SupportReferralForm, SupportReplyForm, SupportTicketForm, TaskGroupForm, TaskLocationForm, UnitForm, UnitTypeForm, UserPinChangeForm, UserPropertyAccessForm, UserProfileForm,
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
    planned_nav = [
        {"label": item["label"], "url": reverse(f"operations:{key}")}
        for key, item in PLANNED_SCREENS.items()
        if item["module"] == screen["module"]
    ]
    return render(request, "booking/operations/planned_screen.html", {
        "title": screen["title"],
        "properties": properties,
        "selected_property": selected,
        "planned_screen": screen,
        "planned_nav": planned_nav,
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
    photo_form = RoomPhotoForm()
    if selected:
        photo_form.fields["unit_type"].queryset = selected.unit_types.filter(is_active=True)
        photo_form.fields["unit"].queryset = selected.units.filter(is_active=True)
    if request.method == "POST" and settings_obj and request.POST.get("action") == "photo":
        photo_form = RoomPhotoForm(request.POST, request.FILES)
        if selected:
            photo_form.fields["unit_type"].queryset = selected.unit_types.filter(is_active=True)
            photo_form.fields["unit"].queryset = selected.units.filter(is_active=True)
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
        for field in ["seo_title", "seo_description", "meta_keywords", "domain", "facebook_url", "instagram_url", "whatsapp_url", "google_business_url", "payment_provider", "payment_public_key"]:
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
        "photos": RoomPhoto.objects.filter(property=selected).select_related("unit_type", "unit") if selected else RoomPhoto.objects.none(),
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
        "room_photo": (RoomPhoto, RoomPhotoForm),
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
        "entity_labels": {"room_group": "Oda grubu", "bed_type": "Yatak tipi", "room_view": "Manzara", "room_location": "Konum", "room_photo": "Oda fotoğrafı", "board_type": "Board Type", "rate_type": "Rate Type"},
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

from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db.models import Q, Sum
from django.db.models import BooleanField
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

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
    MaintenanceStatus,
    MaintenanceTicket,
    OnlineBookingSettings,
    AccessPermission, GuestLoyaltyAccount, GuestProfileExtension, GuestSegment, LoyaltyTier, LoyaltyTransaction, MarketingCampaign, MarketingDelivery, MessageTemplate, OperationalTask, PropertyService, ServiceRequest,
    PropertyRole,
    TaskPriority,
    TaskGroup,
    TaskLocation,
    TaskStatus, UserAccessLog, UserPropertyAccess,
    UnitHousekeepingState,
)
from .forms import (
    BedTypeForm, BoardTypeForm, PropertyProfileForm, PropertySettingsForm, RateTypeForm,
    GuestProfileForm, GuestSegmentForm, LoyaltyTierForm, MarketingCampaignForm, MessageTemplateForm, OperationalTaskForm, PropertyRoleForm, PropertyServiceForm, RoomGroupForm, RoomLocationForm, RoomPhotoForm, RoomViewForm, TaskGroupForm, TaskLocationForm, UnitForm, UnitTypeForm, UserPropertyAccessForm,
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
            "guests": Guest.objects.filter(property=selected).count(),
            "arrivals": ReservationItem.objects.filter(reservation__property=selected, reservation__check_in=today).count(),
            "departures": ReservationItem.objects.filter(reservation__property=selected, reservation__check_out=today).count(),
        }
        recent_tasks = OperationalTask.objects.filter(property=selected).select_related("assigned_to")[:8]
        recent_tickets = MaintenanceTicket.objects.filter(property=selected).select_related("unit")[:8]
    else:
        metrics = {key: 0 for key in ["rooms_total", "occupied", "occupancy_percent", "dirty", "maintenance", "tasks", "guests", "arrivals", "departures"]}
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
            HousekeepingTask.objects.create(
                property=selected, unit=unit,
                status=request.POST.get("status", HousekeepingStatus.DIRTY),
                priority=request.POST.get("priority", TaskPriority.NORMAL),
                assigned_to_id=request.POST.get("assigned_to") or None,
                note=request.POST.get("note", ""),
            )
            UnitHousekeepingState.objects.update_or_create(
                unit=unit,
                defaults={"status": request.POST.get("status", HousekeepingStatus.DIRTY), "note": request.POST.get("note", ""), "changed_by": request.user},
            )
        elif task and request.POST.get("action") == "status":
            status = request.POST.get("status")
            if status in HousekeepingStatus.values:
                task.status = status
                task.inspected_at = timezone.now() if status == HousekeepingStatus.INSPECTION else task.inspected_at
                task.save(update_fields=["status", "inspected_at", "updated_at"])
                UnitHousekeepingState.objects.update_or_create(
                    unit=task.unit,
                    defaults={"status": status, "note": task.note, "changed_by": request.user},
                )
        return redirect(f"{reverse('operations:housekeeping')}?property_id={selected.id}")
    tasks_qs = HousekeepingTask.objects.filter(property=selected).select_related("unit", "assigned_to") if selected else HousekeepingTask.objects.none()
    status = request.GET.get("status")
    if status in HousekeepingStatus.values:
        tasks_qs = tasks_qs.filter(status=status)
    return render(request, "booking/operations/housekeeping.html", {
        "title": "Housekeeping",
        "properties": properties, "selected_property": selected, "tasks": tasks_qs,
        "units": selected.units.select_related("unit_type") if selected else Unit.objects.none(),
        "users": _users_for_property(selected), "status_choices": HousekeepingStatus.choices,
        "priority_choices": TaskPriority.choices,
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
            MaintenanceTicket.objects.create(
                property=selected,
                unit=selected.units.filter(id=request.POST.get("unit_id")).first(),
                title=request.POST["title"], description=request.POST.get("description", ""),
                priority=request.POST.get("priority", TaskPriority.NORMAL),
                assigned_to_id=request.POST.get("assigned_to") or None, created_by=request.user,
                sla_due_at=sla_due_at,
            )
        elif ticket and action == "status" and request.POST.get("status") in MaintenanceStatus.values:
            ticket.status = request.POST["status"]
            ticket.assigned_to_id = request.POST.get("assigned_to") or None
            ticket.resolution_note = request.POST.get("resolution_note", "").strip()
            if ticket.status == MaintenanceStatus.RESOLVED:
                ticket.resolved_at = timezone.now()
            else:
                ticket.resolved_at = None
            ticket.save(update_fields=["status", "assigned_to", "resolution_note", "resolved_at", "updated_at"])
        return redirect(f"{reverse('operations:maintenance')}?property_id={selected.id}")
    tickets = MaintenanceTicket.objects.filter(property=selected).select_related("unit", "assigned_to") if selected else MaintenanceTicket.objects.none()
    return render(request, "booking/operations/maintenance.html", {
        "title": "Teknik Servis",
        "properties": properties, "selected_property": selected, "tickets": tickets,
        "units": selected.units.all() if selected else Unit.objects.none(), "users": _users_for_property(selected),
        "status_choices": MaintenanceStatus.choices, "priority_choices": TaskPriority.choices,
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
                elif obj.status != TaskStatus.DONE:
                    obj.completed_at = None
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
    return render(request, "booking/operations/tasks.html", {
        "title": "Görev Yönetimi",
        "properties": properties, "selected_property": selected, "tasks": tasks_qs,
        "form": form, "task_groups": TaskGroup.objects.filter(property=selected) if selected else TaskGroup.objects.none(),
        "task_locations": TaskLocation.objects.filter(property=selected) if selected else TaskLocation.objects.none(),
        "status_choices": TaskStatus.choices, "priority_choices": TaskPriority.choices,
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
        for field in [f.name for f in OnlineBookingSettings._meta.fields if isinstance(f, BooleanField)]:
            setattr(settings_obj, field, request.POST.get(field) == "on")
        for field in ["seo_title", "seo_description", "meta_keywords", "domain", "payment_provider", "payment_public_key"]:
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
    if selected:
        role_form.fields["permissions"].queryset = AccessPermission.objects.filter(is_active=True)
        access_form.fields["role"].queryset = selected.access_roles.filter(is_active=True)
        access_form.fields["user"].queryset = get_user_model().objects.filter(
            id__in=Membership.objects.filter(
                Q(organization=selected.organization, property__isnull=True) | Q(property=selected), is_active=True,
            ).values_list("user_id", flat=True),
        ).order_by("username")
    if request.method == "POST" and selected:
        action = request.POST.get("action")
        if action == "role" and role_form.is_valid():
            role = role_form.save(commit=False)
            role.property = selected
            role.save()
            role_form.save_m2m()
            messages.success(request, "Property rolü kaydedildi.")
            return redirect(f"{reverse('operations:access_control')}?property_id={selected.id}")
        if action == "access" and access_form.is_valid():
            access = access_form.save(commit=False)
            access.property = selected
            access.save()
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
    return render(request, "booking/operations/access_control.html", {
        "title": "Kullanıcı ve Yetki",
        "properties": properties, "selected_property": selected,
        "memberships": list(memberships) + list(property_memberships),
        "roles": selected.access_roles.prefetch_related("permissions") if selected else PropertyRole.objects.none(),
        "accesses": selected.user_accesses.select_related("user", "role") if selected else UserPropertyAccess.objects.none(),
        "logs": selected.access_logs.select_related("user").all()[:25] if selected else UserAccessLog.objects.none(),
        "role_form": role_form, "access_form": access_form,
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

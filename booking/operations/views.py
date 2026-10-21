from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.db.models import BooleanField
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from booking.reservations.models import Guest, ReservationItem, ReservationStatus, StayStatus
from booking.reservations.views import _business_properties
from booking.tenancy.models import (
    BedType, BoardType, Membership, Property, PropertySettings, RateType,
    RoomGroup, RoomLocation, RoomPhoto, RoomView, Unit,
)

from .models import (
    GuestProfileExtension,
    HousekeepingStatus,
    HousekeepingTask,
    MaintenanceStatus,
    MaintenanceTicket,
    OnlineBookingSettings,
    GuestLoyaltyAccount, GuestProfileExtension, LoyaltyTier, OperationalTask,
    PropertyRole,
    TaskPriority,
    TaskGroup,
    TaskLocation,
    TaskStatus, UserAccessLog, UserPropertyAccess,
    UnitHousekeepingState,
)
from .forms import (
    BedTypeForm, BoardTypeForm, PropertySettingsForm, RateTypeForm,
    GuestProfileForm, LoyaltyTierForm, OperationalTaskForm, RoomGroupForm, RoomLocationForm, RoomPhotoForm, RoomViewForm, TaskGroupForm, TaskLocationForm,
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


@login_required
def housekeeping(request):
    properties, selected = _selected_property(request)
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
        "properties": properties, "selected_property": selected, "tasks": tasks_qs,
        "units": selected.units.select_related("unit_type") if selected else Unit.objects.none(),
        "users": _users_for_property(selected), "status_choices": HousekeepingStatus.choices,
        "priority_choices": TaskPriority.choices,
    })


@login_required
def maintenance(request):
    properties, selected = _selected_property(request)
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
        "properties": properties, "selected_property": selected, "tickets": tickets,
        "units": selected.units.all() if selected else Unit.objects.none(), "users": _users_for_property(selected),
        "status_choices": MaintenanceStatus.choices, "priority_choices": TaskPriority.choices,
    })


@login_required
def tasks(request):
    properties, selected = _selected_property(request)
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
    settings_obj = OnlineBookingSettings.objects.get_or_create(property=selected)[0] if selected else None
    if request.method == "POST" and settings_obj:
        for field in [f.name for f in OnlineBookingSettings._meta.fields if isinstance(f, BooleanField)]:
            setattr(settings_obj, field, request.POST.get(field) == "on")
        for field in ["seo_title", "seo_description", "meta_keywords", "domain"]:
            setattr(settings_obj, field, request.POST.get(field, "").strip())
        settings_obj.save()
        messages.success(request, "Online booking ayarları kaydedildi.")
        return redirect(f"{reverse('operations:online_settings')}?property_id={selected.id}")
    return render(request, "booking/operations/online_settings.html", {
        "properties": properties, "selected_property": selected, "settings": settings_obj,
    })


@login_required
def crm_guests(request):
    properties, selected = _selected_property(request)
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
        return redirect(f"{reverse('operations:crm_guests')}?property_id={selected.id}&q={q}&guest_id={selected_guest.id if selected_guest else ''}")
    return render(request, "booking/operations/crm_guests.html", {
        "properties": properties, "selected_property": selected, "guests": guests, "query": q,
        "selected_guest": selected_guest, "profile_form": profile_form, "tier_form": tier_form,
        "tiers": selected.loyalty_tiers.filter(is_active=True) if selected else LoyaltyTier.objects.none(),
        "loyalty": getattr(selected_guest, "loyalty_account", None) if selected_guest else None,
    })


@login_required
def access_control(request):
    properties, selected = _selected_property(request)
    memberships = Membership.objects.filter(
        organization=selected.organization if selected else None,
        property__isnull=True,
        is_active=True,
    ).select_related("user") if selected else Membership.objects.none()
    property_memberships = Membership.objects.filter(
        property=selected, is_active=True,
    ).select_related("user") if selected else Membership.objects.none()
    return render(request, "booking/operations/access_control.html", {
        "properties": properties, "selected_property": selected,
        "memberships": list(memberships) + list(property_memberships),
        "roles": selected.access_roles.prefetch_related("permissions") if selected else PropertyRole.objects.none(),
        "accesses": selected.user_accesses.select_related("user", "role") if selected else UserPropertyAccess.objects.none(),
        "logs": selected.access_logs.select_related("user").all()[:25] if selected else UserAccessLog.objects.none(),
    })


@login_required
def property_settings(request):
    properties, selected = _selected_property(request)
    settings_obj = PropertySettings.objects.filter(property=selected).first() if selected else None
    form = PropertySettingsForm(request.POST or None, instance=settings_obj)
    if request.method == "POST" and selected and form.is_valid():
        obj = form.save(commit=False)
        obj.property = selected
        obj.save()
        messages.success(request, "Otel ayarları kaydedildi.")
        return redirect(f"{reverse('operations:property_settings')}?property_id={selected.id}")
    return render(request, "booking/operations/property_settings.html", {
        "properties": properties, "selected_property": selected, "form": form,
    })


@login_required
def hotel_dictionaries(request):
    properties, selected = _selected_property(request)
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
    form = form_class(request.POST or None)
    if selected and active == "room_photo":
        form.fields["unit_type"].queryset = selected.unit_types.filter(is_active=True)
        form.fields["unit"].queryset = selected.units.filter(is_active=True)
    if request.method == "POST" and selected and form.is_valid():
        obj = form.save(commit=False)
        obj.property = selected
        obj.save()
        messages.success(request, "Tanım kaydedildi.")
        return redirect(f"{reverse('operations:hotel_dictionaries')}?property_id={selected.id}&entity={active}")
    lists = {key: model.objects.filter(property=selected) if selected else model.objects.none() for key, (model, _) in form_map.items()}
    return render(request, "booking/operations/hotel_dictionaries.html", {
        "properties": properties, "selected_property": selected, "active_entity": active,
        "form": form, "lists": lists, "selected_items": lists[active],
        "entity_labels": {"room_group": "Oda grubu", "bed_type": "Yatak tipi", "room_view": "Manzara", "room_location": "Konum", "room_photo": "Oda fotoğrafı", "board_type": "Board Type", "rate_type": "Rate Type"},
    })


@login_required
def room_rack(request):
    properties, selected = _selected_property(request)
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
                messages.success(request, f"{item.reservation.reference} için check-out tamamlandı.")
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
            rooms.append({"unit": unit, "item": item, "status": rack_status})
    unassigned = ReservationItem.objects.filter(
        reservation__property=selected, unit__isnull=True,
        reservation__status__in=[ReservationStatus.PENDING, ReservationStatus.CONFIRMED],
        reservation__check_in__lte=selected_date, reservation__check_out__gt=selected_date,
    ).select_related("reservation", "reservation__guest", "unit_type") if selected else ReservationItem.objects.none()
    return render(request, "booking/operations/room_rack.html", {
        "properties": properties, "selected_property": selected, "rack_date": selected_date,
        "rooms": rooms, "unassigned": unassigned,
    })

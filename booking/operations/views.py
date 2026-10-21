from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.db.models import BooleanField
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from booking.reservations.models import Guest
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
    TaskPriority,
)
from .forms import (
    BedTypeForm, BoardTypeForm, PropertySettingsForm, RateTypeForm,
    RoomGroupForm, RoomLocationForm, RoomPhotoForm, RoomViewForm,
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
        elif task and request.POST.get("action") == "status":
            status = request.POST.get("status")
            if status in HousekeepingStatus.values:
                task.status = status
                task.inspected_at = timezone.now() if status == HousekeepingStatus.INSPECTION else task.inspected_at
                task.save(update_fields=["status", "inspected_at", "updated_at"])
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
            MaintenanceTicket.objects.create(
                property=selected,
                unit=selected.units.filter(id=request.POST.get("unit_id")).first(),
                title=request.POST["title"], description=request.POST.get("description", ""),
                priority=request.POST.get("priority", TaskPriority.NORMAL),
                assigned_to_id=request.POST.get("assigned_to") or None, created_by=request.user,
            )
        elif ticket and action == "status" and request.POST.get("status") in MaintenanceStatus.values:
            ticket.status = request.POST["status"]
            if ticket.status == MaintenanceStatus.RESOLVED:
                ticket.resolved_at = timezone.now()
            ticket.save(update_fields=["status", "resolved_at", "updated_at"])
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
    tickets = MaintenanceTicket.objects.filter(property=selected) if selected else MaintenanceTicket.objects.none()
    housekeeping_tasks = HousekeepingTask.objects.filter(property=selected) if selected else HousekeepingTask.objects.none()
    return render(request, "booking/operations/tasks.html", {
        "properties": properties, "selected_property": selected, "tickets": tickets,
        "housekeeping_tasks": housekeeping_tasks,
    })


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
    guests = Guest.objects.filter(property=selected).select_related("profile_extension") if selected else Guest.objects.none()
    q = request.GET.get("q", "").strip()
    if q:
        guests = guests.filter(Q(first_name__icontains=q) | Q(last_name__icontains=q) | Q(email__icontains=q) | Q(phone__icontains=q))
    return render(request, "booking/operations/crm_guests.html", {
        "properties": properties, "selected_property": selected, "guests": guests, "query": q,
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

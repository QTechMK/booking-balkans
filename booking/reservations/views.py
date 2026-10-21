from datetime import date
from datetime import timedelta
from urllib.parse import urlparse
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db.models import ProtectedError
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render
from django.urls import reverse
from django.utils.dateparse import parse_date

from booking.tenancy.models import Membership
from booking.tenancy.models import Property
from booking.tenancy.models import RatePlan
from booking.tenancy.models import DailyRate
from booking.tenancy.models import Inventory
from booking.tenancy.models import Unit
from booking.tenancy.models import UnitType
from booking.tenancy.models import BedType
from booking.tenancy.models import RoomAmenity
from booking.tenancy.models import RoomLocation
from booking.tenancy.models import RoomView
from booking.tenancy.models import BoardType
from booking.tenancy.models import RateType
from booking.tenancy.services.availability import get_availability

from .forms import BookingSearchForm
from .forms import GuestBookingForm
from .forms import MarketplaceSearchForm
from .forms import ReservationChannelForm
from .forms import BusinessManualReservationForm
from .forms import BusinessDailyRateForm
from .forms import BusinessInventoryForm
from .forms import BusinessBulkDailyRateForm
from .forms import BusinessBulkInventoryForm
from .forms import BusinessRatePlanForm
from .forms import BusinessUnitForm
from .forms import BusinessUnitTypeForm
from .forms import BusinessChannelRateRuleForm
from .forms import BusinessPriceParityObservationForm
from .models import GuestPortalAccess, Reservation
from .models import ReservationChannel
from .models import ReservationSource
from .models import ReservationStatus
from booking.tenancy.models import ChannelRateRule
from booking.tenancy.models import PriceParityObservation
from .services.booking import book_direct
from .forms import GuestPortalCheckinForm


def _default_search():
    property_ = Property.objects.filter(is_active=True).first()
    rate_plan = (
        RatePlan.objects.filter(property=property_, is_active=True).first()
        if property_
        else None
    )
    start = date.today() + timedelta(days=1)
    return property_, rate_plan, start, start + timedelta(days=2)


def marketplace_search(request):
    start = date.today() + timedelta(days=1)
    end = start + timedelta(days=2)
    form = MarketplaceSearchForm(
        request.GET or None,
        initial={"check_in": start, "check_out": end, "quantity": 1},
    )
    results = []
    searched = bool(request.GET)
    if form.is_valid() and searched:
        cleaned = form.cleaned_data
        properties = Property.objects.filter(is_active=True).order_by("name")
        if cleaned["q"]:
            term = cleaned["q"].strip()
            properties = properties.filter(
                Q(name__icontains=term)
                | Q(city__icontains=term)
                | Q(address__icontains=term)
            )
        for property_ in properties.prefetch_related("rate_plans"):
            rate_plans = list(property_.rate_plans.filter(is_active=True))
            availability = None
            selected_rate_plan = None
            for rate_plan in rate_plans:
                candidate = get_availability(
                    property_id=property_.id,
                    rate_plan_id=rate_plan.id,
                    check_in=cleaned["check_in"],
                    check_out=cleaned["check_out"],
                    quantity=cleaned["quantity"],
                )
                if availability is None or candidate.available:
                    availability = candidate
                    selected_rate_plan = rate_plan
                if candidate.available:
                    break
            if selected_rate_plan:
                booking_query = urlencode(
                    {
                        "property_id": property_.id,
                        "rate_plan_id": selected_rate_plan.id,
                        "check_in": cleaned["check_in"].isoformat(),
                        "check_out": cleaned["check_out"].isoformat(),
                        "quantity": cleaned["quantity"],
                        "source": ReservationSource.MARKETPLACE,
                    }
                )
                results.append(
                    {
                        "property": property_,
                        "rate_plan": selected_rate_plan,
                        "availability": availability,
                        "booking_query": booking_query,
                    }
                )
    return render(
        request,
        "marketplace/search.html",
        {"form": form, "results": results, "searched": searched},
    )


def marketplace_property_detail(request, pk):
    property_ = get_object_or_404(Property, pk=pk, is_active=True)
    start = date.today() + timedelta(days=1)
    end = start + timedelta(days=2)
    form = MarketplaceSearchForm(
        request.GET or None,
        initial={"check_in": start, "check_out": end, "quantity": 1},
    )
    rate_results = []
    if request.GET and form.is_valid():
        cleaned = form.cleaned_data
        check_in = cleaned["check_in"]
        check_out = cleaned["check_out"]
        quantity = cleaned["quantity"]
    else:
        check_in, check_out, quantity = start, end, 1

    for rate_plan in property_.rate_plans.filter(is_active=True).order_by("name"):
        availability = get_availability(
            property_id=property_.id,
            rate_plan_id=rate_plan.id,
            check_in=check_in,
            check_out=check_out,
            quantity=quantity,
        )
        rate_results.append(
            {
                "rate_plan": rate_plan,
                "availability": availability,
                "booking_query": urlencode(
                    {
                        "property_id": property_.id,
                        "rate_plan_id": rate_plan.id,
                        "check_in": check_in.isoformat(),
                        "check_out": check_out.isoformat(),
                        "quantity": quantity,
                        "source": ReservationSource.MARKETPLACE,
                    }
                ),
            }
        )
    return render(
        request,
        "marketplace/property_detail.html",
        {
            "property": property_,
            "form": form,
            "rate_results": rate_results,
            "check_in": check_in,
            "check_out": check_out,
        },
    )


def search(request):
    default_property, default_rate_plan, start, end = _default_search()
    form = BookingSearchForm(
        request.GET or None,
        initial={
            "property_id": default_property.id if default_property else "",
            "rate_plan_id": default_rate_plan.id if default_rate_plan else "",
            "check_in": start,
            "check_out": end,
            "quantity": 1,
        },
    )
    result = None
    selected_rate_plan = default_rate_plan
    if request.GET:
        if form.is_valid():
            selected_rate_plan = get_object_or_404(
                RatePlan,
                id=form.cleaned_data["rate_plan_id"],
                property_id=form.cleaned_data["property_id"],
                is_active=True,
            )
            result = get_availability(
                property_id=selected_rate_plan.property_id,
                rate_plan_id=selected_rate_plan.id,
                check_in=form.cleaned_data["check_in"],
                check_out=form.cleaned_data["check_out"],
                quantity=form.cleaned_data["quantity"],
            )
    rate_plans = (
        RatePlan.objects.filter(property=default_property, is_active=True)
        if default_property
        else RatePlan.objects.none()
    )
    return render(
        request,
        "booking/search.html",
        {
            "form": form,
            "result": result,
            "property": default_property,
            "rate_plan": selected_rate_plan,
            "rate_plans": rate_plans,
        },
    )


def _widget_channel(widget_key):
    return get_object_or_404(
        ReservationChannel.objects.select_related("property").filter(
            widget_key=widget_key,
            source=ReservationSource.WIDGET,
            is_active=True,
            property__is_active=True,
        )
    )


def _widget_origin_matches(request, channel):
    """Return whether the embedding request matches the channel's configured domain."""
    configured = (channel.website_domain or "").strip().lower().rstrip(".")
    if not configured:
        return False
    origin = request.META.get("HTTP_ORIGIN") or request.META.get("HTTP_REFERER")
    if not origin:
        return True
    hostname = (urlparse(origin).hostname or "").lower().rstrip(".")
    configured = configured.removeprefix("https://").removeprefix("http://").split("/")[0]
    return hostname == configured or hostname.endswith(f".{configured}")


def widget_search(request, widget_key):
    channel = _widget_channel(widget_key)
    if not _widget_origin_matches(request, channel):
        return render(request, "booking/widget_denied.html", {"channel": channel}, status=403)

    start = date.today() + timedelta(days=1)
    end = start + timedelta(days=2)
    rate_plan = channel.property.rate_plans.filter(is_active=True).order_by("name").first()
    form = BookingSearchForm(
        request.GET or None,
        initial={
            "property_id": channel.property_id,
            "rate_plan_id": rate_plan.id if rate_plan else "",
            "check_in": start,
            "check_out": end,
            "quantity": 1,
        },
    )
    result = None
    if request.GET and form.is_valid():
        selected_rate_plan = get_object_or_404(
            RatePlan,
            id=form.cleaned_data["rate_plan_id"],
            property_id=channel.property_id,
            is_active=True,
        )
        result = get_availability(
            property_id=channel.property_id,
            rate_plan_id=selected_rate_plan.id,
            check_in=form.cleaned_data["check_in"],
            check_out=form.cleaned_data["check_out"],
            quantity=form.cleaned_data["quantity"],
        )
        rate_plan = selected_rate_plan
    return render(
        request,
        "booking/widget_search.html",
        {
            "channel": channel,
            "form": form,
            "result": result,
            "property": channel.property,
            "rate_plan": rate_plan,
        },
    )


def guest_details(request):
    search_form = BookingSearchForm(request.GET or request.POST or None)
    if not search_form.is_valid():
        return redirect("reservations:search")
    data = search_form.cleaned_data
    rate_plan = get_object_or_404(
        RatePlan,
        id=data["rate_plan_id"],
        property_id=data["property_id"],
        is_active=True,
    )
    availability = get_availability(
        property_id=data["property_id"],
        rate_plan_id=rate_plan.id,
        check_in=data["check_in"],
        check_out=data["check_out"],
        quantity=data["quantity"],
    )
    if not availability.available:
        messages.error(request, "Bu oda seçilen tarihlerde artık müsait değil.")
        return redirect("reservations:search")
    guest_form = GuestBookingForm(request.POST or None)
    if request.method == "POST" and guest_form.is_valid():
        source = request.GET.get("source") or request.POST.get("source", ReservationSource.DIRECT)
        valid_sources = {value for value, _ in ReservationSource.choices}
        if source not in valid_sources:
            source = ReservationSource.DIRECT
        channel_codes = {
            ReservationSource.DIRECT: "tenant_website",
            ReservationSource.MARKETPLACE: "booking_balkans_marketplace",
            ReservationSource.WIDGET: "iframe_widget",
            ReservationSource.B2B: "b2b_portal",
        }
        if source == ReservationSource.WIDGET:
            channel = ReservationChannel.objects.filter(
                property_id=data["property_id"],
                widget_key=request.GET.get("widget_key") or request.POST.get("widget_key"),
                source=ReservationSource.WIDGET,
                is_active=True,
            ).first()
        else:
            channel = ReservationChannel.objects.filter(
                property_id=data["property_id"],
                code=channel_codes.get(source),
                is_active=True,
            ).first()
        if source == ReservationSource.WIDGET and not channel:
            return render(
                request,
                "booking/widget_denied.html",
                {"channel": None},
                status=403,
            )
        try:
            reservation = book_direct(
                property_id=data["property_id"],
                rate_plan_id=rate_plan.id,
                check_in=data["check_in"],
                check_out=data["check_out"],
                quantity=data["quantity"],
                guest_data=guest_form.cleaned_data,
                source=source,
                channel=channel,
            )
        except (IntegrityError, ValidationError):
            messages.error(request, "Rezervasyon oluşturulamadı; oda tekrar kontrol ediliyor.")
        else:
            return redirect(
                f"{reverse('reservations:confirmation')}?reference={reservation.reference}"
            )
    return render(
        request,
        "booking/guest.html",
        {
            "search_form": search_form,
            "guest_form": guest_form,
            "rate_plan": rate_plan,
            "availability": availability,
            "widget_key": request.GET.get("widget_key") or request.POST.get("widget_key", ""),
        },
    )


def confirmation(request):
    reference = request.GET.get("reference")
    reservation = get_object_or_404(
        Reservation,
        reference=reference,
    )
    portal_access, _ = GuestPortalAccess.objects.get_or_create(reservation=reservation)
    from booking.operations.models import OnlineBookingSettings
    settings_obj = OnlineBookingSettings.objects.filter(property=reservation.property).first()
    return render(request, "booking/confirmation.html", {"reservation": reservation, "portal_access": portal_access, "portal_active": bool(settings_obj and settings_obj.guest_portal_active)})


def guest_portal(request, token):
    portal_access = get_object_or_404(
        GuestPortalAccess.objects.select_related("reservation", "reservation__guest", "reservation__property"),
        token=token,
    )
    reservation = portal_access.reservation
    from booking.operations.models import OnlineBookingSettings, PropertyService, ServiceRequest
    settings_obj = OnlineBookingSettings.objects.filter(property=reservation.property).first()
    portal_active = bool(settings_obj and settings_obj.guest_portal_active)
    checkin_active = bool(portal_active and settings_obj.online_checkin_active)
    if request.method == "POST" and request.POST.get("action") == "service_request" and portal_active and settings_obj:
        service = PropertyService.objects.filter(
            id=request.POST.get("service_id"), property=reservation.property, is_active=True, show_online=True,
        ).first()
        flag_by_kind = {
            PropertyService.Kind.EXTRA: "extra_services_active",
            PropertyService.Kind.LATE_CHECKOUT: "late_checkout_active",
            PropertyService.Kind.TRANSFER: "transfer_active",
            PropertyService.Kind.ROOM_UPGRADE: "room_upgrade_active",
        }
        if service and getattr(settings_obj, flag_by_kind[service.kind], False):
            try:
                quantity = max(1, int(request.POST.get("quantity") or 1))
            except ValueError:
                quantity = 1
            ServiceRequest.objects.create(reservation=reservation, service=service, quantity=quantity, note=request.POST.get("note", ""))
            messages.success(request, "Hizmet talebiniz tesise iletildi.")
        else:
            messages.error(request, "Bu hizmet şu anda kullanılamıyor.")
        return redirect("reservations:guest_portal", token=portal_access.token)
    form = GuestPortalCheckinForm(request.POST or None, initial={
        "first_name": reservation.guest.first_name, "last_name": reservation.guest.last_name,
        "phone": reservation.guest.phone,
    })
    if request.method == "POST" and checkin_active and not portal_access.online_checkin_completed and form.is_valid():
        data = form.cleaned_data
        guest = reservation.guest
        guest.first_name, guest.last_name, guest.phone = data["first_name"], data["last_name"], data["phone"]
        guest.save(update_fields=["first_name", "last_name", "phone", "updated_at"])
        portal_access.checkin_data = {key: data[key] for key in ("nationality", "identity_reference")}
        portal_access.online_checkin_completed = True
        portal_access.save(update_fields=["checkin_data", "online_checkin_completed", "updated_at"])
        messages.success(request, "Online check-in tamamlandı.")
        return redirect("reservations:guest_portal", token=portal_access.token)
    flag_by_kind = {
        PropertyService.Kind.EXTRA: "extra_services_active",
        PropertyService.Kind.LATE_CHECKOUT: "late_checkout_active",
        PropertyService.Kind.TRANSFER: "transfer_active",
        PropertyService.Kind.ROOM_UPGRADE: "room_upgrade_active",
    }
    services = [service for service in PropertyService.objects.filter(property=reservation.property, is_active=True, show_online=True) if portal_active and settings_obj and getattr(settings_obj, flag_by_kind[service.kind], False)]
    return render(request, "booking/guest_portal.html", {
        "reservation": reservation, "portal_access": portal_access,
        "settings": settings_obj, "portal_active": portal_active, "checkin_active": checkin_active, "form": form, "services": services,
    })


def _business_properties(user):
    if user.is_superuser:
        return Property.objects.filter(is_active=True)

    memberships = Membership.objects.filter(user=user, is_active=True)
    organization_ids = memberships.values_list("organization_id", flat=True)
    property_ids = memberships.exclude(property_id=None).values_list(
        "property_id", flat=True
    )
    return Property.objects.filter(
        Q(organization_id__in=organization_ids) | Q(id__in=property_ids),
        is_active=True,
    ).distinct()


def _selected_business_property(request):
    properties = _business_properties(request.user).order_by("name")
    property_id = request.POST.get("property_id") or request.GET.get("property_id")
    selected = properties.filter(id=property_id).first() if property_id else None
    return properties, selected or properties.first()


@login_required
def business_inventory(request):
    properties, selected_property = _selected_business_property(request)
    edit_unit_type = selected_property.unit_types.filter(id=request.GET.get("edit_unit_type")).first() if selected_property else None
    edit_unit = selected_property.units.filter(id=request.GET.get("edit_unit")).first() if selected_property else None
    unit_type_form = BusinessUnitTypeForm(instance=edit_unit_type, prefix="unit_type")
    unit_form = BusinessUnitForm(instance=edit_unit, prefix="unit")
    if selected_property:
        unit_form.fields["unit_type"].queryset = selected_property.unit_types.all()
        unit_type_form.fields["room_group"].queryset = selected_property.roomgroup_set.filter(is_active=True)
        unit_type_form.fields["amenities"].queryset = RoomAmenity.objects.filter(property=selected_property, is_active=True)
        unit_form.fields["bed_type"].queryset = BedType.objects.filter(property=selected_property, is_active=True)
        unit_form.fields["room_view"].queryset = RoomView.objects.filter(property=selected_property, is_active=True)
        unit_form.fields["room_location"].queryset = RoomLocation.objects.filter(property=selected_property, is_active=True)
    if request.method == "POST" and selected_property:
        entity = request.POST.get("entity")
        if entity == "unit_type_delete":
            obj = selected_property.unit_types.filter(id=request.POST.get("object_id")).first()
            if obj:
                try:
                    obj.delete()
                except ProtectedError:
                    messages.error(request, "Bu oda tipi ilişkili kayıtlar nedeniyle silinemedi.")
            return redirect(f"{reverse('reservations:business_inventory')}?property_id={selected_property.id}")
        if entity == "unit_delete":
            obj = selected_property.units.filter(id=request.POST.get("object_id")).first()
            if obj:
                try:
                    obj.delete()
                except ProtectedError:
                    messages.error(request, "Bu ünite ilişkili rezervasyonlar nedeniyle silinemedi.")
            return redirect(f"{reverse('reservations:business_inventory')}?property_id={selected_property.id}")
        if entity == "unit_type":
            unit_type_form = BusinessUnitTypeForm(request.POST, instance=edit_unit_type, prefix="unit_type")
            if unit_type_form.is_valid():
                obj = unit_type_form.save(commit=False)
                obj.property = selected_property
                obj.save()
                unit_type_form.save_m2m()
                return redirect(f"{reverse('reservations:business_inventory')}?property_id={selected_property.id}")
        elif entity == "unit":
            unit_form = BusinessUnitForm(request.POST, instance=edit_unit, prefix="unit")
            unit_form.fields["unit_type"].queryset = selected_property.unit_types.all()
            if unit_form.is_valid() and unit_form.cleaned_data["unit_type"].property_id == selected_property.id:
                obj = unit_form.save(commit=False)
                obj.property = selected_property
                obj.save()
                return redirect(f"{reverse('reservations:business_inventory')}?property_id={selected_property.id}")
    unit_types = selected_property.unit_types.prefetch_related("units") if selected_property else UnitType.objects.none()
    units = selected_property.units.select_related("unit_type") if selected_property else Unit.objects.none()
    return render(request, "booking/business/inventory.html", {"properties": properties, "selected_property": selected_property, "unit_type_form": unit_type_form, "unit_form": unit_form, "unit_types": unit_types, "units": units})


@login_required
def business_rate_plans(request):
    properties, selected_property = _selected_business_property(request)
    edit_rate_plan = selected_property.rate_plans.filter(id=request.GET.get("edit_rate_plan")).first() if selected_property else None
    form = BusinessRatePlanForm(instance=edit_rate_plan, prefix="rate")
    if selected_property:
        form.fields["unit_type"].queryset = selected_property.unit_types.all()
        form.fields["board_type"].queryset = BoardType.objects.filter(property=selected_property, is_active=True)
        form.fields["rate_type"].queryset = RateType.objects.filter(property=selected_property, is_active=True)
    if request.method == "POST" and selected_property:
        if request.POST.get("entity") == "rate_delete":
            obj = selected_property.rate_plans.filter(id=request.POST.get("object_id")).first()
            if obj:
                try:
                    obj.delete()
                except ProtectedError:
                    messages.error(request, "Bu rate plan ilişkili kayıtlar nedeniyle silinemedi.")
            return redirect(f"{reverse('reservations:business_rate_plans')}?property_id={selected_property.id}")
        form = BusinessRatePlanForm(request.POST, instance=edit_rate_plan, prefix="rate")
        form.fields["unit_type"].queryset = selected_property.unit_types.all()
        form.fields["board_type"].queryset = BoardType.objects.filter(property=selected_property, is_active=True)
        form.fields["rate_type"].queryset = RateType.objects.filter(property=selected_property, is_active=True)
        if form.is_valid() and form.cleaned_data["unit_type"].property_id == selected_property.id:
            obj = form.save(commit=False)
            obj.property = selected_property
            obj.save()
            return redirect(f"{reverse('reservations:business_rate_plans')}?property_id={selected_property.id}")
    rate_plans = selected_property.rate_plans.select_related("unit_type") if selected_property else RatePlan.objects.none()
    return render(request, "booking/business/rates.html", {"properties": properties, "selected_property": selected_property, "form": form, "rate_plans": rate_plans})


@login_required
def business_rate_calendar(request):
    properties, selected_property = _selected_business_property(request)
    rate_plan_id = request.POST.get("rate_plan_id") or request.GET.get("rate_plan_id")
    rate_plans = selected_property.rate_plans.filter(is_active=True) if selected_property else RatePlan.objects.none()
    selected_rate_plan = rate_plans.filter(id=rate_plan_id).first() if rate_plan_id else rate_plans.first()
    daily_form = BusinessDailyRateForm(prefix="rate")
    inventory_form = BusinessInventoryForm(prefix="inventory")
    bulk_rate_form = BusinessBulkDailyRateForm(prefix="bulk_rate")
    bulk_inventory_form = BusinessBulkInventoryForm(prefix="bulk_inventory")
    if selected_property:
        daily_form.fields["rate_plan"].queryset = rate_plans
        inventory_form.fields["unit_type"].queryset = selected_property.unit_types.all()
        bulk_rate_form.fields["rate_plan"].queryset = rate_plans
        bulk_inventory_form.fields["unit_type"].queryset = selected_property.unit_types.all()
        if selected_rate_plan:
            daily_form.fields["rate_plan"].initial = selected_rate_plan
        first_unit_type = selected_property.unit_types.order_by("name").first()
        if first_unit_type:
            inventory_form.fields["unit_type"].initial = first_unit_type
    if request.method == "POST" and selected_property:
        entity = request.POST.get("entity")
        if entity == "rate":
            daily_form = BusinessDailyRateForm(request.POST, prefix="rate")
            daily_form.fields["rate_plan"].queryset = rate_plans
            if daily_form.is_valid() and daily_form.cleaned_data["rate_plan"].property_id == selected_property.id:
                daily_form.save()
                return redirect(f"{reverse('reservations:business_rate_calendar')}?property_id={selected_property.id}&rate_plan_id={daily_form.cleaned_data['rate_plan'].id}")
        elif entity == "bulk_rate":
            bulk_rate_form = BusinessBulkDailyRateForm(request.POST, prefix="bulk_rate")
            bulk_rate_form.fields["rate_plan"].queryset = rate_plans
            if bulk_rate_form.is_valid() and bulk_rate_form.cleaned_data["rate_plan"].property_id == selected_property.id:
                data = bulk_rate_form.cleaned_data
                current = data["start_date"]
                while current <= data["end_date"]:
                    DailyRate.objects.update_or_create(
                        rate_plan=data["rate_plan"], date=current,
                        defaults={"amount": data["amount"], "min_nights": data["min_nights"], "max_nights": data["max_nights"], "is_closed": data["is_closed"]},
                    )
                    current += timedelta(days=1)
                return redirect(f"{reverse('reservations:business_rate_calendar')}?property_id={selected_property.id}&rate_plan_id={data['rate_plan'].id}")
        elif entity == "inventory":
            inventory_form = BusinessInventoryForm(request.POST, prefix="inventory")
            inventory_form.fields["unit_type"].queryset = selected_property.unit_types.all()
            if inventory_form.is_valid() and inventory_form.cleaned_data["unit_type"].property_id == selected_property.id:
                obj = inventory_form.save(commit=False)
                obj.property = selected_property
                obj.save()
                return redirect(f"{reverse('reservations:business_rate_calendar')}?property_id={selected_property.id}&rate_plan_id={rate_plan_id or ''}")
        elif entity == "bulk_inventory":
            bulk_inventory_form = BusinessBulkInventoryForm(request.POST, prefix="bulk_inventory")
            bulk_inventory_form.fields["unit_type"].queryset = selected_property.unit_types.all()
            if bulk_inventory_form.is_valid() and bulk_inventory_form.cleaned_data["unit_type"].property_id == selected_property.id:
                data = bulk_inventory_form.cleaned_data
                current = data["start_date"]
                while current <= data["end_date"]:
                    Inventory.objects.update_or_create(
                        property=selected_property, unit_type=data["unit_type"], date=current,
                        defaults={"total_capacity": data["total_capacity"], "blocked_capacity": data["blocked_capacity"], "is_closed": data["is_closed"]},
                    )
                    current += timedelta(days=1)
                return redirect(f"{reverse('reservations:business_rate_calendar')}?property_id={selected_property.id}&rate_plan_id={rate_plan_id or ''}")
    daily_rates = selected_rate_plan.daily_rates.order_by("-date")[:31] if selected_rate_plan else DailyRate.objects.none()
    inventory_days = selected_property.inventory_days.select_related("unit_type").order_by("-date")[:31] if selected_property else Inventory.objects.none()
    return render(request, "booking/business/rate_calendar.html", {"properties": properties, "selected_property": selected_property, "rate_plans": rate_plans, "selected_rate_plan": selected_rate_plan, "daily_form": daily_form, "inventory_form": inventory_form, "bulk_rate_form": bulk_rate_form, "bulk_inventory_form": bulk_inventory_form, "daily_rates": daily_rates, "inventory_days": inventory_days})


@login_required
def business_reservation_list(request):
    properties = _business_properties(request.user).order_by("name")
    property_id = request.GET.get("property_id")
    selected_property = properties.filter(id=property_id).first() if property_id else None
    if not selected_property:
        selected_property = properties.first()

    reservations = Reservation.objects.none()
    if selected_property:
        reservations = (
            Reservation.objects.filter(property=selected_property)
            .select_related("guest", "property", "channel")
            .prefetch_related("items")
        )

        status = request.GET.get("status")
        if status in {choice for choice, _ in ReservationStatus.choices}:
            reservations = reservations.filter(status=status)

        source = request.GET.get("source")
        if source in {choice for choice, _ in ReservationSource.choices}:
            reservations = reservations.filter(source=source)

        channel_id = request.GET.get("channel")
        if channel_id and selected_property.reservation_channels.filter(
            id=channel_id, is_active=True
        ).exists():
            reservations = reservations.filter(channel_id=channel_id)

        search_term = request.GET.get("q", "").strip()
        if search_term:
            reservations = reservations.filter(
                Q(reference__icontains=search_term)
                | Q(guest__first_name__icontains=search_term)
                | Q(guest__last_name__icontains=search_term)
                | Q(guest__email__icontains=search_term)
            )

        check_in_from = request.GET.get("check_in_from")
        if check_in_from:
            reservations = reservations.filter(check_in__gte=check_in_from)

        check_in_to = request.GET.get("check_in_to")
        if check_in_to:
            reservations = reservations.filter(check_in__lte=check_in_to)

    return render(
        request,
        "booking/business/reservations/list.html",
        {
            "properties": properties,
            "selected_property": selected_property,
            "reservations": reservations,
            "status_choices": ReservationStatus.choices,
            "source_choices": ReservationSource.choices,
            "channel_choices": selected_property.reservation_channels.filter(
                is_active=True
            ),
            "filters": request.GET,
        },
    )


@login_required
def business_reservation_detail(request, pk):
    reservation = get_object_or_404(
        Reservation.objects.filter(property__in=_business_properties(request.user))
        .select_related("guest", "property", "channel")
        .prefetch_related("items__unit_type", "items__rate_plan", "items__unit"),
        pk=pk,
    )
    return render(
        request,
        "booking/business/reservations/detail.html",
        {"reservation": reservation},
    )


@login_required
def business_reservation_calendar(request):
    properties, selected_property = _selected_business_property(request)
    start = parse_date(request.GET.get("start", "")) or date.today()
    end = parse_date(request.GET.get("end", "")) or (start + timedelta(days=30))
    if end < start:
        end = start + timedelta(days=30)
    reservations = (
        Reservation.objects.filter(
            property=selected_property,
            check_in__lte=end,
            check_out__gte=start,
        ).select_related("guest", "channel").order_by("check_in", "reference")
        if selected_property
        else Reservation.objects.none()
    )
    calendar_days = [start + timedelta(days=index) for index in range((end - start).days + 1)]
    calendar_rows = [
        {"reservation": reservation, "occupied_dates": [reservation.check_in + timedelta(days=index) for index in range((reservation.check_out - reservation.check_in).days)]}
        for reservation in reservations
    ]
    return render(
        request,
        "booking/business/reservations/calendar.html",
        {"properties": properties, "selected_property": selected_property, "reservations": reservations, "calendar_days": calendar_days, "calendar_rows": calendar_rows, "start": start, "end": end},
    )
@login_required
def business_channel_list(request):
    properties = _business_properties(request.user).order_by("name")
    property_id = request.POST.get("property_id") or request.GET.get("property_id")
    selected_property = properties.filter(id=property_id).first() if property_id else None
    if not selected_property:
        selected_property = properties.first()

    edit_channel = selected_property.reservation_channels.filter(id=request.GET.get("edit_channel")).first() if selected_property else None
    form = ReservationChannelForm(instance=edit_channel, data=request.POST or None)
    if request.method == "POST" and selected_property:
        if request.POST.get("entity") == "channel_delete":
            channel = selected_property.reservation_channels.filter(id=request.POST.get("object_id")).first()
            if channel:
                channel.delete()
            return redirect(f"{reverse('reservations:business_channel_list')}?property_id={selected_property.id}")
        if not form.is_valid():
            channels = selected_property.reservation_channels.all()
            return render(request, "booking/business/reservations/channels.html", {"properties": properties, "selected_property": selected_property, "channels": channels, "form": form})
        channel = form.save(commit=False)
        channel.property = selected_property
        channel.save()
        return redirect(
            f"{reverse('reservations:business_channel_list')}?property_id={selected_property.id}"
        )

    channels = (
        selected_property.reservation_channels.all()
        if selected_property
        else ReservationChannel.objects.none()
    )


@login_required
def business_channel_rate_rules(request):
    properties, selected_property = _selected_business_property(request)
    edit_rule = (
        selected_property.channel_rate_rules.filter(id=request.GET.get("edit_rule")).first()
        if selected_property else None
    )
    form = (
        BusinessChannelRateRuleForm(instance=edit_rule, property_=selected_property)
        if selected_property else None
    )
    if request.method == "POST" and selected_property:
        if request.POST.get("entity") == "rate_rule_delete":
            rule = selected_property.channel_rate_rules.filter(id=request.POST.get("object_id")).first()
            if rule:
                rule.delete()
            return redirect(f"{reverse('reservations:business_channel_rate_rules')}?property_id={selected_property.id}")
        form = BusinessChannelRateRuleForm(request.POST, instance=edit_rule, property_=selected_property)
        if form.is_valid():
            rule = form.save(commit=False)
            rule.property = selected_property
            rule.save()
            return redirect(f"{reverse('reservations:business_channel_rate_rules')}?property_id={selected_property.id}")
    rules = (
        selected_property.channel_rate_rules.select_related("channel", "rate_plan")
        if selected_property else ChannelRateRule.objects.none()
    )
    return render(request, "booking/business/channel_rate_rules.html", {
        "properties": properties,
        "selected_property": selected_property,
        "form": form,
        "rules": rules,
    })


@login_required
def business_price_parity(request):
    properties, selected_property = _selected_business_property(request)
    form = BusinessPriceParityObservationForm(property_=selected_property) if selected_property else None
    if request.method == "POST" and selected_property:
        form = BusinessPriceParityObservationForm(request.POST, property_=selected_property)
        if form.is_valid():
            observation = form.save(commit=False)
            observation.property = selected_property
            observation.save()
            return redirect(f"{reverse('reservations:business_price_parity')}?property_id={selected_property.id}")
    observations = (
        selected_property.price_parity_observations.select_related("rate_plan", "channel")
        if selected_property else PriceParityObservation.objects.none()
    )
    status = request.GET.get("status")
    if status in {choice for choice, _ in PriceParityObservation._meta.get_field("status").choices}:
        observations = observations.filter(status=status)
    return render(request, "booking/business/price_parity.html", {
        "properties": properties,
        "selected_property": selected_property,
        "form": form,
        "observations": observations,
    })
    return render(
        request,
        "booking/business/reservations/channels.html",
        {
            "properties": properties,
            "selected_property": selected_property,
            "channels": channels,
            "form": form,
        },
    )


@login_required
def business_reservation_create(request):
    properties = _business_properties(request.user).order_by("name")
    property_id = request.POST.get("property") or request.GET.get("property_id")
    selected_property = properties.filter(id=property_id).first() if property_id else properties.first()
    form = BusinessManualReservationForm(
        request.POST or None,
        properties=properties,
        selected_property=selected_property,
    )
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        availability = get_availability(
            property_id=data["property"].id,
            rate_plan_id=data["rate_plan"].id,
            check_in=data["check_in"],
            check_out=data["check_out"],
            quantity=data["quantity"],
        )
        if not availability.available:
            form.add_error(None, "Seçilen tarihlerde yeterli müsaitlik yok.")
        else:
            reservation = book_direct(
                property_id=data["property"].id,
                rate_plan_id=data["rate_plan"].id,
                check_in=data["check_in"],
                check_out=data["check_out"],
                quantity=data["quantity"],
                guest_data={
                    "first_name": data["first_name"],
                    "last_name": data["last_name"],
                    "email": data["email"],
                    "phone": data["phone"],
                    "country": data["country"],
                },
                source=ReservationSource.MANUAL,
                channel=data["channel"],
                created_by=request.user,
            )
            return redirect("reservations:business_reservation_detail", pk=reservation.pk)
    return render(
        request,
        "booking/business/reservations/create.html",
        {"form": form, "properties": properties, "selected_property": selected_property},
    )

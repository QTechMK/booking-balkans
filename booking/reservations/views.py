from datetime import date
from datetime import timedelta
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render
from django.urls import reverse

from booking.tenancy.models import Membership
from booking.tenancy.models import Property
from booking.tenancy.models import RatePlan
from booking.tenancy.services.availability import get_availability

from .forms import BookingSearchForm
from .forms import GuestBookingForm
from .forms import MarketplaceSearchForm
from .models import Reservation
from .models import ReservationSource
from .models import ReservationStatus
from .services.booking import book_direct


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
        try:
            reservation = book_direct(
                property_id=data["property_id"],
                rate_plan_id=rate_plan.id,
                check_in=data["check_in"],
                check_out=data["check_out"],
                quantity=data["quantity"],
                guest_data=guest_form.cleaned_data,
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
        },
    )


def confirmation(request):
    reference = request.GET.get("reference")
    reservation = get_object_or_404(
        Reservation,
        reference=reference,
    )
    return render(request, "booking/confirmation.html", {"reservation": reservation})


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
            .select_related("guest", "property")
            .prefetch_related("items")
        )

        status = request.GET.get("status")
        if status in {choice for choice, _ in ReservationStatus.choices}:
            reservations = reservations.filter(status=status)

        source = request.GET.get("source")
        if source in {choice for choice, _ in ReservationSource.choices}:
            reservations = reservations.filter(source=source)

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
            "filters": request.GET,
        },
    )


@login_required
def business_reservation_detail(request, pk):
    reservation = get_object_or_404(
        Reservation.objects.filter(property__in=_business_properties(request.user))
        .select_related("guest", "property")
        .prefetch_related("items__unit_type", "items__rate_plan", "items__unit"),
        pk=pk,
    )
    return render(
        request,
        "booking/business/reservations/detail.html",
        {"reservation": reservation},
    )

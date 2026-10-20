from datetime import date
from datetime import timedelta

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render
from django.urls import reverse

from booking.tenancy.models import Property
from booking.tenancy.models import RatePlan
from booking.tenancy.services.availability import get_availability

from .forms import BookingSearchForm
from .forms import GuestBookingForm
from .models import Reservation
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

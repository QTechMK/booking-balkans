from django.urls import path

from . import views

app_name = "reservations"

urlpatterns = [
    path("search/", views.search, name="search"),
    path("guest/", views.guest_details, name="guest_details"),
    path("confirmation/", views.confirmation, name="confirmation"),
    path(
        "business/reservations/",
        views.business_reservation_list,
        name="business_reservation_list",
    ),
]

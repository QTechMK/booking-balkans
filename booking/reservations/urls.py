from django.urls import path

from . import views

app_name = "reservations"

urlpatterns = [
    path("search/", views.search, name="search"),
    path("guest/", views.guest_details, name="guest_details"),
    path("confirmation/", views.confirmation, name="confirmation"),
    path("guest/portal/<uuid:token>/", views.guest_portal, name="guest_portal"),
    path("widget/<uuid:widget_key>/", views.widget_search, name="widget_search"),
    path(
        "business/reservations/",
        views.business_reservation_list,
        name="business_reservation_list",
    ),
    path(
        "business/reservations/new/",
        views.business_reservation_create,
        name="business_reservation_create",
    ),
    path(
        "business/reservations/<int:pk>/",
        views.business_reservation_detail,
        name="business_reservation_detail",
    ),
    path("business/reservations/calendar/", views.business_reservation_calendar, name="business_reservation_calendar"),
    path(
        "business/channels/",
        views.business_channel_list,
        name="business_channel_list",
    ),
    path(
        "business/channel-rules/",
        views.business_channel_rate_rules,
        name="business_channel_rate_rules",
    ),
    path(
        "business/price-parity/",
        views.business_price_parity,
        name="business_price_parity",
    ),
    path("business/inventory/", views.business_inventory, name="business_inventory"),
    path("business/rates/", views.business_rate_plans, name="business_rate_plans"),
    path("business/rate-calendar/", views.business_rate_calendar, name="business_rate_calendar"),
]

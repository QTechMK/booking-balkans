from django.urls import path

from . import views

app_name = "operations"

urlpatterns = [
    path("business/dashboard/", views.dashboard, name="dashboard"),
    path("business/reports/", views.reports, name="reports"),
    path("business/property-settings/", views.property_settings, name="property_settings"),
    path("business/hotel-dictionaries/", views.hotel_dictionaries, name="hotel_dictionaries"),
    path("business/room-master/", views.room_master, name="room_master"),
    path("business/room-rack/", views.room_rack, name="room_rack"),
    path("business/housekeeping/", views.housekeeping, name="housekeeping"),
    path("business/maintenance/", views.maintenance, name="maintenance"),
    path("business/tasks/", views.tasks, name="tasks"),
    path("business/online-settings/", views.online_settings, name="online_settings"),
    path("business/crm/guests/", views.crm_guests, name="crm_guests"),
    path("business/crm/marketing/", views.crm_marketing, name="crm_marketing"),
    path("business/access/", views.access_control, name="access_control"),
]

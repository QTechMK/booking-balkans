from django.urls import path

from .views import availability_api

app_name = "tenancy"

urlpatterns = [
    path(
        "properties/<int:property_id>/availability/",
        availability_api,
        name="availability",
    ),
]

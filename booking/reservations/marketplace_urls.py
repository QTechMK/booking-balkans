from django.urls import path

from . import views

app_name = "marketplace"

urlpatterns = [
    path("", views.marketplace_search, name="search"),
    path("property/<int:pk>/", views.marketplace_property_detail, name="property_detail"),
]

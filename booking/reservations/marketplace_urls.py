from django.urls import path

from . import views

app_name = "marketplace"

urlpatterns = [
    path("", views.marketplace_search, name="search"),
]

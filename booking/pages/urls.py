from django.urls import path

from .views import dynamic_pages_view
from .views import root_page_view

app_name = "pages"

urlpatterns = [
    path("", root_page_view, name="dashboard"),
    path("<str:template_name>/", dynamic_pages_view, name="dynamic_pages"),
]

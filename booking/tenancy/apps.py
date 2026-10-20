from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class TenancyConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "booking.tenancy"
    verbose_name = _("Organizations and Properties")

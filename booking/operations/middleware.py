from urllib.parse import urlencode

from allauth.mfa.utils import is_mfa_enabled
from django.contrib.auth import REDIRECT_FIELD_NAME
from django.db.models import Q
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone

from .models import UserPropertyAccess


class RequiredPropertyMFAMiddleware:
    """Require configured MFA before entering property business screens."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if self._must_enroll(request):
            target = reverse("mfa_index")
            query = urlencode({REDIRECT_FIELD_NAME: request.get_full_path()})
            return redirect(f"{target}?{query}")
        return self.get_response(request)

    @staticmethod
    def _must_enroll(request):
        if not request.user.is_authenticated or not request.path.startswith("/booking/business/"):
            return False
        if request.user.is_superuser or request.path.startswith("/accounts/"):
            return False
        property_id = request.POST.get("property_id") or request.GET.get("property_id")
        accesses = UserPropertyAccess.objects.filter(
            user=request.user,
            is_active=True,
            role__is_active=True,
            two_factor_required=True,
        ).filter(Q(valid_from__isnull=True) | Q(valid_from__lte=timezone.localdate())) \
         .filter(Q(valid_until__isnull=True) | Q(valid_until__gte=timezone.localdate()))
        if property_id:
            accesses = accesses.filter(property_id=property_id)
        else:
            accesses = accesses.distinct()
        return accesses.exists() and not is_mfa_enabled(request.user)

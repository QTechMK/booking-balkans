from urllib.parse import urlencode

from allauth.mfa.utils import is_mfa_enabled
from django.contrib.auth import REDIRECT_FIELD_NAME
from django.db.models import Q
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.http import HttpResponseForbidden

from .models import UserAccessLog, UserPropertyAccess


class RequiredPropertyMFAMiddleware:
    """Require configured MFA before entering property business screens."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if self._must_enroll(request):
            target = reverse("mfa_index")
            query = urlencode({REDIRECT_FIELD_NAME: request.get_full_path()})
            return redirect(f"{target}?{query}")
        if self._blocked_by_network_policy(request):
            return HttpResponseForbidden("Bu kullanıcı için IP veya cihaz erişim kısıtı nedeniyle erişim engellendi.")
        return self.get_response(request)

    @staticmethod
    def _must_enroll(request):
        if not request.user.is_authenticated or not request.path.startswith("/booking/business/"):
            return False
        if request.user.is_superuser or request.path.startswith("/accounts/"):
            return False
        property_id = request.POST.get("property_id") or request.GET.get("property_id")
        try:
            property_id = int(property_id) if property_id else None
        except (TypeError, ValueError):
            property_id = None
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

    @staticmethod
    def _blocked_by_network_policy(request):
        if not request.user.is_authenticated or not request.path.startswith("/booking/business/"):
            return False
        if request.user.is_superuser or request.path.startswith("/accounts/"):
            return False
        accesses = UserPropertyAccess.objects.filter(
            user=request.user, is_active=True, role__is_active=True,
        ).filter(Q(valid_from__isnull=True) | Q(valid_from__lte=timezone.localdate())) \
         .filter(Q(valid_until__isnull=True) | Q(valid_until__gte=timezone.localdate()))
        restricted = [access for access in accesses if access.allowed_ip or access.device_label]
        if not restricted:
            return False
        ip = (request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip() or request.META.get("REMOTE_ADDR"))
        user_agent = request.META.get("HTTP_USER_AGENT", "")
        if any((not access.allowed_ip or access.allowed_ip == ip) and (not access.device_label or access.device_label.lower() in user_agent.lower()) for access in restricted):
            return False
        for access in restricted:
            UserAccessLog.objects.create(
                user=request.user, property=access.property, successful=False,
                event="network_policy_denied", ip_address=ip or None, user_agent=user_agent[:500],
            )
        return True

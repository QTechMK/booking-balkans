from django.contrib.auth.signals import user_logged_in, user_login_failed
from django.dispatch import receiver

from booking.tenancy.models import Membership

from .models import UserAccessLog


def _client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    return (forwarded.split(",")[0].strip() if forwarded else request.META.get("REMOTE_ADDR")) or None


@receiver(user_logged_in)
def record_successful_login(sender, request, user, **kwargs):
    properties = Membership.objects.filter(user=user, is_active=True).exclude(property__isnull=True).values_list("property_id", flat=True)
    property_ids = set(properties)
    organization_ids = Membership.objects.filter(user=user, is_active=True, property__isnull=True).values_list("organization_id", flat=True)
    from booking.tenancy.models import Property
    property_ids.update(Property.objects.filter(organization_id__in=organization_ids, is_active=True).values_list("id", flat=True))
    if not property_ids:
        property_ids = {None}
    for property_id in property_ids:
        UserAccessLog.objects.create(
            user=user, property_id=property_id, successful=True, event="login",
            ip_address=_client_ip(request), user_agent=request.META.get("HTTP_USER_AGENT", "")[:500],
        )


@receiver(user_login_failed)
def record_failed_login(sender, credentials, request, **kwargs):
    UserAccessLog.objects.create(
        successful=False, event="login_failed", ip_address=_client_ip(request),
        user_agent=request.META.get("HTTP_USER_AGENT", "")[:500] if request else "",
    )

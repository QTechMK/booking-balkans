from datetime import date
from decimal import InvalidOperation

from django.http import JsonResponse
from django.views.decorators.http import require_GET

from .services.availability import get_availability


def _parse_date(value: str | None, field_name: str) -> date:
    if not value:
        raise ValueError(f"{field_name} is required")
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{field_name} must be YYYY-MM-DD") from error


@require_GET
def availability_api(request, property_id: int):
    """Return priced availability for a property and rate plan."""

    try:
        rate_plan_id = int(request.GET.get("rate_plan", ""))
        check_in = _parse_date(request.GET.get("check_in"), "check_in")
        check_out = _parse_date(request.GET.get("check_out"), "check_out")
        quantity = int(request.GET.get("quantity", "1"))
        result = get_availability(
            property_id=property_id,
            rate_plan_id=rate_plan_id,
            check_in=check_in,
            check_out=check_out,
            quantity=quantity,
        )
    except (TypeError, ValueError, InvalidOperation) as error:
        return JsonResponse({"detail": str(error)}, status=400)

    return JsonResponse(
        {
            "available": result.available,
            "property_id": property_id,
            "rate_plan_id": rate_plan_id,
            "check_in": result.check_in.isoformat(),
            "check_out": result.check_out.isoformat(),
            "nights": result.nights,
            "total_amount": str(result.total_amount),
            "reason": result.reason,
            "days": [
                {
                    "date": day.date.isoformat(),
                    "amount": str(day.amount),
                    "capacity": day.capacity,
                }
                for day in result.days
            ],
        }
    )

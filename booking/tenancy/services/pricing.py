from decimal import Decimal, ROUND_HALF_UP

from django.db.models import Q

from booking.tenancy.models import ChannelRateRule, ChannelRateRuleType
from booking.tenancy.models import PriceParityObservation


MONEY_QUANTUM = Decimal("0.01")


def calculate_channel_amount(*, amount, channel, rate_plan=None):
    """Return the direct amount adjusted by the first matching active rule."""

    base_amount = Decimal(str(amount))
    rule = (
        ChannelRateRule.objects.filter(
            property=channel.property,
            channel=channel,
            is_active=True,
        )
        .filter(Q(rate_plan=rate_plan) | Q(rate_plan__isnull=True))
        .order_by("priority", "-rate_plan_id", "id")
        .first()
    )
    if rule is None:
        return base_amount.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)

    if rule.rule_type == ChannelRateRuleType.PERCENT:
        result = base_amount * (Decimal("1") + rule.adjustment / Decimal("100"))
    else:
        result = base_amount + rule.adjustment
    return max(result, Decimal("0")).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def record_price_parity_observation(**kwargs):
    """Persist an internal parity observation with fail-closed classification."""

    observation = PriceParityObservation(**kwargs)
    observation.full_clean()
    observation.save()
    return observation

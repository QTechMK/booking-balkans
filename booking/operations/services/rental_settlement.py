from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from ..models import CreditAccount, Invoice, RentalAuditEvent, RentalHandover, RentalInvoice, RentalSettlement


def calculate_rental_settlement(booking):
    """Calculate post-return charges from the recorded handover and damage data."""
    pickup = booking.handovers.filter(kind=RentalHandover.Kind.PICKUP).order_by("recorded_at").first()
    returned = booking.handovers.filter(kind=RentalHandover.Kind.RETURN).order_by("-recorded_at").first()
    rate = booking.rental_rate
    extra_km = 0
    extra_km_amount = Decimal("0")
    if pickup and returned and pickup.mileage is not None and returned.mileage is not None and rate:
        included = (rate.included_km_per_day or 0) * max(1, (booking.dropoff_at.date() - booking.pickup_at.date()).days)
        extra_km = max(0, returned.mileage - pickup.mileage - included)
        extra_km_amount = Decimal(extra_km) * (rate.extra_km_rate or Decimal("0"))

    late_minutes = 0
    late_amount = Decimal("0")
    if returned and returned.recorded_at > booking.dropoff_at and rate:
        late_minutes = max(0, int((returned.recorded_at - booking.dropoff_at).total_seconds() // 60))
        late_days = Decimal(late_minutes) / Decimal(24 * 60)
        late_amount = (rate.daily_rate or Decimal("0")) * late_days

    damage_amount = sum(
        (case.estimated_cost for case in booking.damage_cases.filter(status__in=["open", "estimated"])),
        Decimal("0"),
    )
    total = extra_km_amount + late_amount + damage_amount
    return {
        "extra_km": extra_km,
        "extra_mileage_amount": extra_km_amount,
        "late_minutes": late_minutes,
        "late_return_amount": late_amount,
        "damage_amount": damage_amount,
        "fuel_amount": Decimal("0"),
        "total_amount": total,
        "currency": booking.currency,
    }


@transaction.atomic
def upsert_rental_settlement(*, booking, actor=None):
    quote = calculate_rental_settlement(booking)
    settlement, _ = RentalSettlement.objects.select_for_update().get_or_create(
        booking=booking,
        defaults={"currency": booking.currency},
    )
    settlement.status = RentalSettlement.Status.READY
    settlement.extra_mileage_amount = quote["extra_mileage_amount"]
    settlement.late_return_amount = quote["late_return_amount"]
    settlement.damage_amount = quote["damage_amount"]
    settlement.fuel_amount = quote["fuel_amount"]
    settlement.total_amount = quote["total_amount"]
    settlement.currency = quote["currency"]
    settlement.details = {
        "extra_km": quote["extra_km"],
        "late_minutes": quote["late_minutes"],
        "calculated_at": timezone.now().isoformat(),
    }
    settlement.save()
    RentalAuditEvent.objects.create(
        property=booking.property, booking=booking, actor=actor,
        action="rental_settlement_calculated", source="system",
        payload={"settlement_id": settlement.id, "total_amount": str(settlement.total_amount)},
    )
    return settlement


@transaction.atomic
def issue_settlement_invoice(*, settlement, actor=None, credit_account=None):
    """Create the official invoice for a post-rental settlement once.

    ``credit_account`` is optional because a hotel may require an explicit
    accounting-account selection before posting a receivable. When supplied,
    the account balance is increased atomically with invoice creation.
    """
    settlement = RentalSettlement.objects.select_for_update().select_related("booking", "booking__property", "booking__driver_profile").get(pk=settlement.pk)
    existing = RentalInvoice.objects.select_related("invoice").filter(booking=settlement.booking, invoice_kind="settlement").first()
    if existing:
        return existing.invoice
    if settlement.status not in {RentalSettlement.Status.READY, RentalSettlement.Status.INVOICED}:
        raise ValueError("Settlement must be ready before invoicing.")
    booking = settlement.booking
    driver = booking.driver_profile
    customer_name = (driver.full_name if driver else booking.customer_name) or "Rental customer"
    invoice_number = f"RSET-{booking.property_id}-{booking.id}-{settlement.id}"
    lines = []
    for code, description, amount in (
        ("extra_mileage", "Fazla kilometre", settlement.extra_mileage_amount),
        ("late_return", "Geç teslim", settlement.late_return_amount),
        ("damage", "Hasar maliyeti", settlement.damage_amount),
        ("fuel", "Yakıt farkı", settlement.fuel_amount),
    ):
        if amount:
            lines.append({"code": code, "description": description, "quantity": 1, "unit_price": str(amount), "amount": str(amount)})
    invoice = Invoice.objects.create(
        property=booking.property,
        reservation=booking.reservation,
        number=invoice_number,
        status=Invoice.Status.ISSUED,
        issue_date=timezone.localdate(),
        currency=settlement.currency,
        subtotal=settlement.total_amount,
        tax=Decimal("0"),
        total=settlement.total_amount,
        customer_name=customer_name,
        customer_tax_number="",
        notes=f"Araç kiralama settlement: {booking.confirmation_code}",
        lines=lines,
        created_by=actor,
    )
    RentalInvoice.objects.create(booking=booking, invoice=invoice, invoice_kind="settlement")
    if credit_account:
        account = CreditAccount.objects.select_for_update().get(pk=credit_account.pk)
        if account.property_id != booking.property_id or account.currency != settlement.currency:
            raise ValueError("Credit account must belong to the booking property and currency.")
        account.balance = account.balance + settlement.total_amount
        account.save(update_fields=["balance"])
    settlement.status = RentalSettlement.Status.INVOICED
    settlement.details = {**(settlement.details or {}), "invoice_id": invoice.id, "invoiced_at": timezone.now().isoformat()}
    settlement.save(update_fields=["status", "details", "calculated_at"])
    RentalAuditEvent.objects.create(
        property=booking.property, booking=booking, actor=actor,
        action="rental_settlement_invoiced", source="system",
        payload={"settlement_id": settlement.id, "invoice_id": invoice.id, "credit_account_id": credit_account.id if credit_account else None},
    )
    return invoice

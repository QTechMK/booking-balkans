from django.db import transaction
from django.utils import timezone

from ..models import EInvoiceTransmission, Invoice, RentalAuditEvent


def build_invoice_export(invoice):
    """Build a provider-neutral payload without sending data externally."""
    rental_invoice = getattr(invoice, "rental_invoice", None)
    booking = rental_invoice.booking if rental_invoice else None
    return {
        "schema": "booking-balkans.invoice.v1",
        "invoice": {
            "id": invoice.id,
            "number": invoice.number,
            "status": invoice.status,
            "issue_date": invoice.issue_date.isoformat(),
            "due_date": invoice.due_date.isoformat() if invoice.due_date else None,
            "currency": invoice.currency,
            "subtotal": str(invoice.subtotal),
            "tax": str(invoice.tax),
            "total": str(invoice.total),
            "customer_name": invoice.customer_name,
            "customer_tax_number": invoice.customer_tax_number,
            "notes": invoice.notes,
            "lines": invoice.lines or [],
        },
        "property_id": invoice.property_id,
        "reservation_id": invoice.reservation_id,
        "rental": {
            "booking_id": booking.id,
            "confirmation_code": booking.confirmation_code,
            "invoice_kind": rental_invoice.invoice_kind,
        } if booking else None,
    }


@transaction.atomic
def queue_invoice_export(*, invoice, provider="manual", actor=None):
    """Queue an invoice for an external e-invoice/accounting adapter.

    This deliberately does not call a provider. Credentials and provider-specific
    response handling belong to the later F6 adapter integration.
    """
    invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
    if invoice.status == Invoice.Status.CANCELLED:
        raise ValueError("Cancelled invoices cannot be exported.")
    payload = build_invoice_export(invoice)
    transmission, _ = EInvoiceTransmission.objects.select_for_update().get_or_create(
        invoice=invoice,
        defaults={"property": invoice.property, "provider": provider, "payload": payload},
    )
    transmission.property = invoice.property
    transmission.provider = provider
    transmission.status = EInvoiceTransmission.Status.QUEUED
    transmission.payload = payload
    transmission.error_message = ""
    transmission.save(update_fields=["property", "provider", "status", "payload", "error_message", "updated_at"])
    rental_invoice = getattr(invoice, "rental_invoice", None)
    if rental_invoice:
        RentalAuditEvent.objects.create(
            property=invoice.property,
            booking=rental_invoice.booking,
            actor=actor,
            action="invoice_export_queued",
            source="system",
            payload={"invoice_id": invoice.id, "transmission_id": transmission.id, "provider": provider},
        )
    return transmission

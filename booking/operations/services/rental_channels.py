import hashlib
import hmac
import json

import requests
from django.conf import settings
from django.utils import timezone

from booking.operations.models import RentalChannelConnection, RentalChannelSyncEvent
from booking.operations.models import ParkingLot


class RentalChannelConfigurationError(RuntimeError):
    pass


class RentalChannelProviderError(RuntimeError):
    pass


def queue_channel_event(*, connection: RentalChannelConnection, event_type: str, payload: dict):
    """Persist a channel event without calling an external provider."""
    if not connection.is_active:
        raise RentalChannelConfigurationError("Channel connection is inactive.")
    return RentalChannelSyncEvent.objects.create(
        property=connection.property,
        channel=connection.code,
        event_type=event_type,
        external_reference=str(payload.get("external_reference") or "")[:180],
        status="pending",
        payload=payload,
    )


def queue_first_party_event(*, connection: RentalChannelConnection, event_type: str, payload: dict):
    """Queue an event specifically for a Booking Balkans-owned portal."""
    if connection.channel_type != RentalChannelConnection.ChannelType.FIRST_PARTY:
        raise RentalChannelConfigurationError("Connection is not a first-party portal channel.")
    return queue_channel_event(connection=connection, event_type=event_type, payload=payload)


def queue_property_first_party_event(*, property_, event_type: str, payload: dict):
    """Fan out one booking event to every active owned portal of a property."""
    connections = RentalChannelConnection.objects.filter(
        property=property_, channel_type=RentalChannelConnection.ChannelType.FIRST_PARTY, is_active=True,
    )
    return [
        queue_first_party_event(connection=connection, event_type=event_type, payload=payload)
        for connection in connections
    ]


def queue_first_party_reservation_event(*, booking, entity: str, event_type: str):
    """Fan out a rental or parking reservation lifecycle event."""
    is_rental = entity == "rentals"
    payload = {
        "entity": entity,
        "booking_id": booking.id,
        "confirmation_code": booking.confirmation_code,
        "status": booking.status,
        "currency": booking.currency,
        "source": booking.source,
    }
    if is_rental:
        payload.update({"vehicle_id": booking.vehicle_id, "total_amount": str(booking.total_amount)})
    else:
        payload.update({"parking_lot_id": booking.parking_lot_id, "amount": str(booking.amount)})
    return queue_property_first_party_event(property_=booking.property, event_type=event_type, payload=payload)


def build_first_party_snapshot(*, property_, entity: str):
    """Build the shared price/inventory representation for owned portals."""
    if entity == "rentals":
        vehicles = []
        for vehicle in property_.vehicles.filter(is_active=True, online_enabled=True).prefetch_related("rental_rates"):
            vehicles.append({
                "id": vehicle.id, "code": vehicle.code, "name": vehicle.name,
                "class": vehicle.vehicle_class, "rates": [
                    {"id": rate.id, "code": rate.name, "daily": str(rate.daily_rate),
                     "weekly": str(rate.weekly_rate), "monthly": str(rate.monthly_rate),
                     "currency": rate.currency}
                    for rate in vehicle.rental_rates.filter(is_active=True)
                ],
            })
        return {"entity": "rentals", "vehicles": vehicles}
    lots = []
    for lot in ParkingLot.objects.filter(property=property_, is_active=True, booking_enabled=True).prefetch_related("spaces"):
        lots.append({
            "id": lot.id, "code": lot.code, "name": lot.name, "capacity": lot.capacity,
            "currency": lot.currency, "hourly_rate": str(lot.hourly_rate),
            "daily_rate": str(lot.daily_rate), "daily_max_rate": str(lot.daily_max_rate),
            "spaces": [{"id": space.id, "code": space.code, "floor": space.floor,
                        "zone": space.zone, "status": space.status}
                       for space in lot.spaces.filter(is_active=True)],
        })
    return {"entity": "parking", "parking_lots": lots}


def queue_first_party_snapshot(*, property_, entity: str):
    """Queue inventory and rate snapshots for every owned portal."""
    payload = build_first_party_snapshot(property_=property_, entity=entity)
    events = queue_property_first_party_event(property_=property_, event_type="inventory_snapshot", payload=payload)
    events.extend(queue_property_first_party_event(property_=property_, event_type="rate_snapshot", payload=payload))
    return events


def push_channel_event(*, connection: RentalChannelConnection, event_type: str, payload: dict):
    """Send an inventory/rate/reservation event and persist the result in the sync log."""
    if not connection.is_active or not connection.endpoint_url:
        raise RentalChannelConfigurationError("Channel endpoint is not configured.")
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    secret = getattr(settings, "FLEET_CHANNEL_API_SECRET", "") or getattr(settings, "FLEET_CHANNEL_WEBHOOK_SECRET", "")
    headers = {"Content-Type": "application/json", "X-Fleet-Event": event_type}
    if secret:
        headers["X-Fleet-Signature"] = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    event = RentalChannelSyncEvent.objects.create(
        property=connection.property, channel=connection.code, event_type=event_type,
        external_reference=str(payload.get("external_reference") or "")[:180], status="pending", payload=payload,
    )
    try:
        response = requests.post(connection.endpoint_url, data=body, headers=headers, timeout=15)
    except requests.RequestException as exc:
        event.status = "failed"
        event.error_message = str(exc)[:4000]
        event.save(update_fields=["status", "error_message"])
        raise RentalChannelProviderError("Channel provider connection failed.") from exc
    if not response.ok:
        event.status = "failed"
        event.error_message = f"HTTP {response.status_code}"
        event.save(update_fields=["status", "error_message"])
        raise RentalChannelProviderError(f"Channel provider returned HTTP {response.status_code}.")
    event.status = "sent"
    event.save(update_fields=["status"])
    connection.last_sync_at = event.occurred_at
    connection.last_sync_status = "sent"
    connection.save(update_fields=["last_sync_at", "last_sync_status"])
    return event


def dispatch_queued_first_party_events(*, limit=100, execute=False):
    """Dispatch pending first-party events whose portal endpoint is configured."""
    events = RentalChannelSyncEvent.objects.filter(status="pending").order_by("occurred_at", "id")[:limit]
    result = {"queued": 0, "sent": 0, "failed": 0, "skipped": 0}
    for event in events:
        result["queued"] += 1
        connection = RentalChannelConnection.objects.filter(
            property=event.property, code=event.channel,
            channel_type=RentalChannelConnection.ChannelType.FIRST_PARTY, is_active=True,
        ).first()
        if not connection or not connection.endpoint_url:
            result["skipped"] += 1
            continue
        if not execute:
            continue
        body = json.dumps(event.payload, separators=(",", ":"), sort_keys=True).encode()
        secret = getattr(settings, "FLEET_CHANNEL_API_SECRET", "") or getattr(settings, "FLEET_CHANNEL_WEBHOOK_SECRET", "")
        headers = {"Content-Type": "application/json", "X-Fleet-Event": event.event_type}
        if secret:
            headers["X-Fleet-Signature"] = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        try:
            response = requests.post(connection.endpoint_url, data=body, headers=headers, timeout=15)
        except requests.RequestException as exc:
            event.status = "failed"
            event.error_message = str(exc)[:4000]
            event.save(update_fields=["status", "error_message"])
            result["failed"] += 1
            continue
        if not response.ok:
            event.status = "failed"
            event.error_message = f"HTTP {response.status_code}"
            event.save(update_fields=["status", "error_message"])
            result["failed"] += 1
            continue
        event.status = "sent"
        event.error_message = ""
        event.save(update_fields=["status", "error_message"])
        connection.last_sync_at = timezone.now()
        connection.last_sync_status = "sent"
        connection.save(update_fields=["last_sync_at", "last_sync_status"])
        result["sent"] += 1
    return result

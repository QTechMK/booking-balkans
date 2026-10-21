#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${1:-/var/www/booking-balkans}"
SITE_URL="${2:-https://bookingbalkans.com.tr}"
SERVICE_NAME="${SERVICE_NAME:-booking-balkans.service}"

cd "$APP_DIR"
git pull --ff-only origin main

source .venv/bin/activate
python manage.py check
python manage.py migrate --noinput
python manage.py collectstatic --noinput

sudo systemctl restart "$SERVICE_NAME"
sudo systemctl is-active --quiet "$SERVICE_NAME"

HEAD="$(git rev-parse --short HEAD)"
echo "Deployed commit: $HEAD"

for asset in \
    "/static/css/hotel-manager.css" \
    "/static/tixia/css/style.css"; do
    asset_status="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 20 "$SITE_URL$asset")"
    if [[ "$asset_status" != "200" ]]; then
        echo "$asset beklenen 200 yerine $asset_status döndürdü" >&2
        exit 1
    fi
done

business_routes=(
    "/booking/business/dashboard/"
    "/booking/business/reports/"
    "/booking/business/property-settings/"
    "/booking/business/hotel-dictionaries/"
    "/booking/business/room-master/"
    "/booking/business/room-rack/"
    "/booking/business/housekeeping/"
    "/booking/business/maintenance/"
    "/booking/business/tasks/"
    "/booking/business/online-settings/"
    "/booking/business/crm/guests/"
    "/booking/business/crm/marketing/"
    "/booking/business/access/"
)

for route in "${business_routes[@]}"; do
    route_status="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 20 "$SITE_URL$route")"
    case "$route_status" in
        301|302) ;;
        *)
            echo "$route beklenen login yönlendirmesi yerine $route_status döndürdü" >&2
            exit 1
            ;;
    esac
done

echo "Production smoke test başarılı: ${#business_routes[@]} business route, Tixia CSS ve hotel-manager.css doğrulandı"

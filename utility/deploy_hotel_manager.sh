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

static_status="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 20 "$SITE_URL/static/css/hotel-manager.css")"
if [[ "$static_status" != "200" ]]; then
    echo "hotel-manager.css beklenen 200 yerine $static_status döndürdü" >&2
    exit 1
fi

dashboard_status="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 20 "$SITE_URL/booking/business/dashboard/")"
case "$dashboard_status" in
    301|302) ;;
    *)
        echo "business dashboard beklenen login yönlendirmesi yerine $dashboard_status döndürdü" >&2
        exit 1
        ;;
esac

echo "Production smoke test başarılı: static=200, dashboard=$dashboard_status"

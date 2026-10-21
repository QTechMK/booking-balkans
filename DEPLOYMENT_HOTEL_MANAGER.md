# Booking Balkans Hotel Manager Deployment

## Production deploy

Tekrarlanabilir deploy ve smoke test için:

```bash
cd /var/www/booking-balkans
bash utility/deploy_hotel_manager.sh /var/www/booking-balkans https://bookingbalkans.com.tr
```

Script; GitHub pull, Django check, migration, static toplama, servis restartı,
static CSS kontrolü ve login yönlendirmeli business dashboard kontrolünü yapar.

Elle çalıştırma seçeneği:

```bash
cd /var/www/booking-balkans
git pull --ff-only origin main
source .venv/bin/activate
python manage.py check
python manage.py migrate --noinput
python manage.py collectstatic --noinput
sudo systemctl restart booking-balkans.service
sudo systemctl status booking-balkans.service --no-pager
git rev-parse --short HEAD
```

The expected commit is the latest commit shown by `git log -1 --oneline` on GitHub.

## Required environment values

Keep these in the server environment, never in Git:

```env
PAYMENT_STRIPE_SECRET_KEY=
PAYMENT_STRIPE_WEBHOOK_SECRET=
PAYMENT_PAYPAL_CLIENT_ID=
PAYMENT_PAYPAL_CLIENT_SECRET=
PAYMENT_PAYPAL_BASE_URL=https://api-m.sandbox.paypal.com
MARKETING_SMS_WEBHOOK_URL=
MARKETING_SMS_WEBHOOK_TOKEN=
MARKETING_WHATSAPP_WEBHOOK_URL=
MARKETING_WHATSAPP_WEBHOOK_TOKEN=
```

Correct the PayPal URL to `https://api-m.sandbox.paypal.com` for sandbox or the production PayPal endpoint before enabling PayPal.

Stripe webhook:

```text
https://bookingbalkans.com.tr/booking/webhooks/stripe/
```

## CRM dispatch

Run from a cron or worker after SMTP/provider settings are configured:

```bash
cd /var/www/booking-balkans
source .venv/bin/activate
python manage.py dispatch_marketing --limit 100
```

Unconfigured SMS/WhatsApp channels remain queued. Provider failures are recorded as failed deliveries.

## Business panel smoke URLs

After logging in, verify:

```text
/booking/business/dashboard/
/booking/business/property-settings/
/booking/business/hotel-dictionaries/
/booking/business/room-master/
/booking/business/room-rack/
/booking/business/housekeeping/
/booking/business/maintenance/
/booking/business/tasks/
/booking/business/online-settings/
/booking/business/crm/guests/
/booking/business/crm/marketing/
/booking/business/access/
/booking/business/reports/
```

Expected unauthenticated response for protected routes is a redirect to the login screen, not a 404.

## Local verification

```powershell
.venv\Scripts\python.exe manage.py check
.venv\Scripts\python.exe -m pytest -q booking/reservations booking/operations booking/tenancy --disable-warnings
```

from django.db import migrations, models
import django.db.models.deletion


def seed_default_channels(apps, schema_editor):
    Property = apps.get_model("tenancy", "Property")
    ReservationChannel = apps.get_model("reservations", "ReservationChannel")
    defaults = [
        ("reception", "Resepsiyon", "manual", 10),
        ("walk_in", "Walk-in", "manual", 20),
        ("phone", "Telefon", "manual", 30),
        ("email", "E-posta", "manual", 40),
        ("whatsapp", "WhatsApp", "manual", 50),
        ("other", "Diğer", "manual", 60),
        ("booking_balkans_marketplace", "Booking Balkans Marketplace", "marketplace", 100),
        ("tenant_website", "Tesis web sitesi", "direct", 110),
        ("iframe_widget", "Iframe widget", "widget", 120),
        ("b2b_portal", "B2B portal", "b2b", 130),
    ]
    for property_ in Property.objects.all().iterator():
        for code, name, source, sort_order in defaults:
            ReservationChannel.objects.get_or_create(
                property=property_,
                code=code,
                defaults={
                    "name": name,
                    "source": source,
                    "sort_order": sort_order,
                },
            )


class Migration(migrations.Migration):

    dependencies = [
        ("reservations", "0003_reservationitem_checked_in_at_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="ReservationChannel",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.SlugField(max_length=80)),
                ("name", models.CharField(max_length=120)),
                ("source", models.CharField(choices=[("direct", "Direct"), ("marketplace", "Marketplace"), ("widget", "Widget"), ("b2b", "B2B"), ("manual", "Manual"), ("channel_manager", "Channel Manager")], default="manual", max_length=24)),
                ("is_active", models.BooleanField(default=True)),
                ("sort_order", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("property", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="reservation_channels", to="tenancy.property")),
            ],
            options={
                "ordering": ["sort_order", "name"],
                "indexes": [models.Index(fields=["property", "is_active", "sort_order"], name="reservation_propert_422dd5_idx")],
            },
        ),
        migrations.AddConstraint(
            model_name="reservationchannel",
            constraint=models.UniqueConstraint(fields=("property", "code"), name="unique_reservation_channel_per_property"),
        ),
        migrations.AddField(
            model_name="reservation",
            name="channel",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="reservations", to="reservations.reservationchannel"),
        ),
        migrations.RunPython(seed_default_channels, migrations.RunPython.noop),
    ]

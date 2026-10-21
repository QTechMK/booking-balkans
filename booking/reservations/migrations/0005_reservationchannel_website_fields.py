import uuid

from django.db import migrations, models


def populate_widget_keys(apps, schema_editor):
    ReservationChannel = apps.get_model("reservations", "ReservationChannel")
    for channel in ReservationChannel.objects.filter(widget_key__isnull=True).iterator():
        channel.widget_key = uuid.uuid4()
        channel.save(update_fields=["widget_key"])


class Migration(migrations.Migration):

    dependencies = [
        ("reservations", "0004_reservationchannel_reservation_channel"),
    ]

    operations = [
        migrations.AddField(
            model_name="reservationchannel",
            name="website_domain",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="reservationchannel",
            name="website_name",
            field=models.CharField(blank=True, max_length=160),
        ),
        migrations.AddField(
            model_name="reservationchannel",
            name="website_url",
            field=models.URLField(blank=True),
        ),
        migrations.AddField(
            model_name="reservationchannel",
            name="widget_key",
            field=models.UUIDField(blank=True, editable=False, null=True),
        ),
        migrations.RunPython(
            code=populate_widget_keys,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name="reservationchannel",
            name="widget_key",
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
    ]

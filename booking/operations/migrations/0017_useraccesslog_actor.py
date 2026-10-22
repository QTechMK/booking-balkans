from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("operations", "0016_user_property_security_controls"),
    ]

    operations = [
        migrations.AddField(
            model_name="useraccesslog",
            name="actor",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="access_actions",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("operations", "0011_onlinebookingsettings_deposit_percent_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="operationaltask",
            name="completion_note",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="operationaltask",
            name="completed_by",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="completed_operational_tasks", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name="operationaltask",
            name="sla_due_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="housekeepingtask",
            name="inspected_by",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="inspected_housekeeping_tasks", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name="housekeepingtask",
            name="shift",
            field=models.CharField(blank=True, max_length=40),
        ),
        migrations.AddField(
            model_name="maintenanceticket",
            name="actual_cost",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True),
        ),
        migrations.AddField(
            model_name="maintenanceticket",
            name="estimated_cost",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True),
        ),
        migrations.AddField(
            model_name="maintenanceticket",
            name="resolved_by",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="resolved_maintenance_tickets", to=settings.AUTH_USER_MODEL),
        ),
    ]

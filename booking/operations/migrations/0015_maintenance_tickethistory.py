import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("operations", "0014_housekeeping_supervisor_approval"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="MaintenanceTicketHistory",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("status", models.CharField(choices=[("open", "Open"), ("in_progress", "In progress"), ("waiting", "Waiting"), ("resolved", "Resolved"), ("cancelled", "Cancelled")], max_length=24)),
                ("resolution_note", models.TextField(blank=True)),
                ("estimated_cost", models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
                ("actual_cost", models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("assigned_to", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="maintenance_history_assignments", to=settings.AUTH_USER_MODEL)),
                ("changed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="maintenance_history_changes", to=settings.AUTH_USER_MODEL)),
                ("property", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="maintenance_history", to="tenancy.property")),
                ("ticket", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="history", to="operations.maintenanceticket")),
            ],
            options={
                "ordering": ["-created_at"],
                "indexes": [models.Index(fields=["property", "ticket", "created_at"], name="operations__propert_9008f8_idx")],
            },
        ),
    ]

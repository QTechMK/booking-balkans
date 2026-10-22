import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("operations", "0012_operational_sla_housekeeping_shift_maintenance_costs"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="HousekeepingTaskHistory",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("status", models.CharField(choices=[("clean", "Clean"), ("dirty", "Dirty"), ("in_progress", "Cleaning"), ("inspection", "Inspection"), ("out_of_service", "Out of service")], max_length=24)),
                ("shift", models.CharField(blank=True, max_length=40)),
                ("note", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("assigned_to", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="housekeeping_history_assignments", to=settings.AUTH_USER_MODEL)),
                ("changed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="housekeeping_history_changes", to=settings.AUTH_USER_MODEL)),
                ("property", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="housekeeping_history", to="tenancy.property")),
                ("task", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="history", to="operations.housekeepingtask")),
                ("unit", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="housekeeping_history", to="tenancy.unit")),
            ],
            options={
                "ordering": ["-created_at"],
                "indexes": [models.Index(fields=["property", "unit", "created_at"], name="operations__propert_cb4691_idx")],
            },
        ),
    ]

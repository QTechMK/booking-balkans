from django.db import migrations


def seed_reports_permission(apps, schema_editor):
    AccessPermission = apps.get_model("operations", "AccessPermission")
    AccessPermission.objects.update_or_create(
        code="operations.reports.view",
        defaults={"name": "Otel raporlarını görüntüleme", "module": "reports", "action": "view", "is_active": True},
    )


def remove_reports_permission(apps, schema_editor):
    apps.get_model("operations", "AccessPermission").objects.filter(code="operations.reports.view").delete()


class Migration(migrations.Migration):
    dependencies = [("operations", "0009_propertyservice_servicerequest_and_more")]
    operations = [migrations.RunPython(seed_reports_permission, remove_reports_permission)]

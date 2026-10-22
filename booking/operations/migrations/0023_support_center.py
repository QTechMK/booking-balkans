from django.db import migrations


def seed_support_permission(apps, schema_editor):
    AccessPermission = apps.get_model("operations", "AccessPermission")
    AccessPermission.objects.get_or_create(
        code="operations.support.manage",
        defaults={"name": "Destek merkezi yönetimi", "module": "support", "action": "manage", "is_active": True},
    )


def remove_support_permission(apps, schema_editor):
    apps.get_model("operations", "AccessPermission").objects.filter(code="operations.support.manage").delete()


class Migration(migrations.Migration):
    dependencies = [("operations", "0022_supporteducationrequest_supportfaqcategory_and_more")]
    operations = [migrations.RunPython(seed_support_permission, remove_support_permission)]

from django.db import migrations


PERMISSIONS = (
    ("operations.dashboard.view", "Hotel dashboard görüntüleme", "dashboard", "view"),
    ("operations.property.settings.manage", "Property settings yönetimi", "property", "manage"),
    ("operations.hotel.dictionaries.manage", "Hotel dictionaries yönetimi", "hotel", "manage"),
    ("operations.room.master.manage", "Room master yönetimi", "room", "manage"),
    ("operations.front.office.manage", "Front office ve room rack", "front_office", "manage"),
    ("operations.housekeeping.manage", "Housekeeping yönetimi", "housekeeping", "manage"),
    ("operations.maintenance.manage", "Teknik servis yönetimi", "maintenance", "manage"),
    ("operations.tasks.manage", "Görev yönetimi", "tasks", "manage"),
    ("operations.online_settings.manage", "Online booking ayarları", "online_booking", "manage"),
    ("operations.crm.guests.view", "CRM misafirleri görüntüleme", "crm", "view"),
    ("operations.crm.marketing.manage", "CRM pazarlama yönetimi", "crm", "manage"),
    ("operations.access.manage", "Kullanıcı ve yetki yönetimi", "access", "manage"),
)


def seed_permissions(apps, schema_editor):
    AccessPermission = apps.get_model("operations", "AccessPermission")
    for code, name, module, action in PERMISSIONS:
        AccessPermission.objects.update_or_create(
            code=code,
            defaults={"name": name, "module": module, "action": action, "is_active": True},
        )


def remove_permissions(apps, schema_editor):
    AccessPermission = apps.get_model("operations", "AccessPermission")
    AccessPermission.objects.filter(code__in=[item[0] for item in PERMISSIONS]).delete()


class Migration(migrations.Migration):
    dependencies = [("operations", "0007_marketingdelivery")]
    operations = [migrations.RunPython(seed_permissions, remove_permissions)]

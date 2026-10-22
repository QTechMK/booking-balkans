from django.db import migrations


PERMISSIONS = (
    ("operations.financial.invoices.view", "Faturaları görüntüleme", "financial", "invoices_view"),
    ("operations.financial.invoices.manage", "Faturaları yönetme", "financial", "invoices_manage"),
    ("operations.financial.payments.view", "Ödemeleri görüntüleme", "financial", "payments_view"),
    ("operations.financial.payments.manage", "Ödeme alma ve iade", "financial", "payments_manage"),
    ("operations.financial.reports.view", "Finans raporları", "financial", "reports_view"),
    ("operations.pos.access", "POS erişimi", "pos", "access"),
    ("operations.pos.cash.manage", "POS kasa işlemleri", "pos", "cash_manage"),
    ("operations.pos.reports.view", "POS raporları", "pos", "reports_view"),
    ("operations.access.audit.view", "Yetki ve giriş audit logları", "access", "audit_view"),
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
    dependencies = [("operations", "0017_useraccesslog_actor")]
    operations = [migrations.RunPython(seed_permissions, remove_permissions)]

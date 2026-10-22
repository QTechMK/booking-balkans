from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("operations", "0015_maintenance_tickethistory"),
    ]

    operations = [
        migrations.AddField(model_name="userpropertyaccess", name="allowed_ip", field=models.GenericIPAddressField(blank=True, null=True)),
        migrations.AddField(model_name="userpropertyaccess", name="device_label", field=models.CharField(blank=True, max_length=120)),
        migrations.AddField(model_name="userpropertyaccess", name="pin_hash", field=models.CharField(blank=True, max_length=128)),
        migrations.AddField(model_name="userpropertyaccess", name="purchase_approval_required", field=models.BooleanField(default=False)),
        migrations.AddField(model_name="userpropertyaccess", name="bypass_price_control", field=models.BooleanField(default=False)),
        migrations.AddField(model_name="userpropertyaccess", name="own_cash_only", field=models.BooleanField(default=False)),
        migrations.AddField(model_name="userpropertyaccess", name="pos_access", field=models.BooleanField(default=False)),
        migrations.AddField(model_name="userpropertyaccess", name="financial_access", field=models.BooleanField(default=False)),
    ]

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("operations", "0018_seed_financial_access_permissions")]
    operations = [
        migrations.AddField(model_name="onlinebookingsettings", name="facebook_url", field=models.URLField(blank=True)),
        migrations.AddField(model_name="onlinebookingsettings", name="instagram_url", field=models.URLField(blank=True)),
        migrations.AddField(model_name="onlinebookingsettings", name="whatsapp_url", field=models.URLField(blank=True)),
        migrations.AddField(model_name="onlinebookingsettings", name="google_business_url", field=models.URLField(blank=True)),
    ]

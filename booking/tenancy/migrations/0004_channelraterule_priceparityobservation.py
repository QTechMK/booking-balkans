import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tenancy", "0003_rateplan_dailyrate_raterestriction_season_and_more"),
        ("reservations", "0005_reservationchannel_website_fields"),
    ]

    operations = [
        migrations.CreateModel(
            name="ChannelRateRule",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=160)),
                ("rule_type", models.CharField(choices=[("percent", "Percentage"), ("fixed", "Fixed amount")], default="percent", max_length=12)),
                ("adjustment", models.DecimalField(decimal_places=2, max_digits=8)),
                ("priority", models.PositiveIntegerField(default=0)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("channel", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="rate_rules", to="reservations.reservationchannel")),
                ("property", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="channel_rate_rules", to="tenancy.property")),
                ("rate_plan", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="channel_rate_rules", to="tenancy.rateplan")),
            ],
            options={"ordering": ["priority", "name"]},
        ),
        migrations.CreateModel(
            name="PriceParityObservation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("competitor_name", models.CharField(max_length=160)),
                ("check_in", models.DateField()),
                ("check_out", models.DateField()),
                ("adults", models.PositiveIntegerField(default=1)),
                ("children", models.PositiveIntegerField(default=0)),
                ("currency", models.CharField(default="TRY", max_length=3)),
                ("direct_amount", models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
                ("competitor_amount", models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
                ("terms_match", models.BooleanField(default=False)),
                ("status", models.CharField(choices=[("below", "Direct price is lower"), ("equal", "Prices are equal"), ("above", "Direct price is higher"), ("uncomparable", "Not comparable")], default="uncomparable", max_length=16)),
                ("terms_snapshot", models.JSONField(blank=True, default=dict)),
                ("observed_at", models.DateTimeField(auto_now_add=True)),
                ("channel", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="price_parity_observations", to="reservations.reservationchannel")),
                ("property", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="price_parity_observations", to="tenancy.property")),
                ("rate_plan", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="price_parity_observations", to="tenancy.rateplan")),
            ],
            options={"ordering": ["-observed_at"]},
        ),
        migrations.AddIndex(model_name="channelraterule", index=models.Index(fields=["property", "channel", "is_active"], name="tenancy_cha_propert_918812_idx")),
        migrations.AddIndex(model_name="channelraterule", index=models.Index(fields=["rate_plan", "is_active"], name="tenancy_cha_rate_pl_3743d9_idx")),
        migrations.AddIndex(model_name="priceparityobservation", index=models.Index(fields=["property", "observed_at"], name="tenancy_pri_propert_f597e5_idx")),
        migrations.AddIndex(model_name="priceparityobservation", index=models.Index(fields=["property", "status", "observed_at"], name="tenancy_pri_propert_49a319_idx")),
    ]

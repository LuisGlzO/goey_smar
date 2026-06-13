from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("monitor", "0002_rename_alert_check")]

    operations = [
        migrations.RenameIndex(
            model_name="alert",
            old_name="monitor_ale_product_431d9c_idx",
            new_name="monitor_ale_product_cd8cfb_idx",
        ),
        migrations.RenameIndex(
            model_name="productcheck",
            old_name="monitor_pro_product_7e3aba_idx",
            new_name="monitor_pro_product_e7cef4_idx",
        ),
    ]

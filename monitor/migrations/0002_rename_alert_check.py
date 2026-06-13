from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("monitor", "0001_initial")]

    operations = [
        migrations.RenameField(
            model_name="alert",
            old_name="check",
            new_name="product_check",
        ),
    ]

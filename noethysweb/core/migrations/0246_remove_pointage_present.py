from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0245_auto_20260403_0737'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='pointage',
            name='present',
        ),
    ]

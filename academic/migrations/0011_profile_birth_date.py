from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('academic', '0010_medicalsupply_image_url'),
    ]

    operations = [
        migrations.AddField(
            model_name='profile',
            name='birth_date',
            field=models.DateField(blank=True, null=True),
        ),
    ]

# Generated by Django 4.0.3 on 2022-12-07 11:57

import core.models.uploads
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0002_initial_data'),
    ]

    operations = [
        migrations.CreateModel(
            name='UploadFile',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('username', models.CharField(max_length=100)),
                ('course', models.CharField(max_length=500)),
                ('test_name', models.CharField(max_length=100)),
                ('timestamp', models.CharField(max_length=200)),
                ('image', models.ImageField(blank=True, null=True, upload_to=core.models.uploads.snapshots_directory_path)),
            ],
        ),
    ]

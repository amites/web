# -*- coding: utf-8 -*-
# Generated by Django 1.11 on 2017-10-09 11:22
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('marketing', '0005_emailsubscriber_priv'),
    ]

    operations = [
        migrations.AddField(
            model_name='emailsubscriber',
            name='newsletter',
            field=models.BooleanField(default=True),
        ),
    ]

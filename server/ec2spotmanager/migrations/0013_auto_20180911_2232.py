# -*- coding: utf-8 -*-
# Generated by Django 1.11.13 on 2018-09-11 22:32
from __future__ import unicode_literals

from django.db import migrations, models
import ec2spotmanager.models


class Migration(migrations.Migration):

    dependencies = [
        ('ec2spotmanager', '0012_auto_20180911_0807'),
    ]

    operations = [
        migrations.RenameField(
            model_name='poolconfiguration',
            old_name='ec2_userdata_macros',
            new_name='userdata_macros',
        ),
        migrations.RenameField(
            model_name='poolconfiguration',
            old_name='ec2_userdata_file',
            new_name='userdata_file'
        ),
    ]

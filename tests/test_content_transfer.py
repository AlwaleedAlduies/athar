import hashlib
import io
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import TestCase, override_settings

from apps.accounts.models import User
from apps.ai.models import ProviderConfiguration
from apps.history.models import Entity, HistoricalEvent, StoryPassage
from apps.knowledge.models import Evidence


class ContentTransferTests(TestCase):
    def command(self, **kwargs):
        call_command('import_sqlite_content', stdout=io.StringIO(), **kwargs)

    @override_settings(DEBUG=False)
    def test_production_import_is_refused(self):
        with self.assertRaisesMessage(CommandError, 'Development only'):
            self.command(apply=True)

    @override_settings(DEBUG=True)
    def test_sqlite_target_is_refused(self):
        with patch.object(connection, 'vendor', 'sqlite'):
            with self.assertRaisesMessage(CommandError, 'Target must be development PostgreSQL'):
                self.command(apply=True)

    @override_settings(DEBUG=True)
    def test_existing_content_is_never_overwritten(self):
        if connection.vendor != 'postgresql':
            self.skipTest('PostgreSQL required')
        entity = Entity.objects.create(title='Existing content', slug='existing-content', kind='place')
        with self.assertRaisesMessage(CommandError, 'refusing to overwrite'):
            self.command(apply=True)
        self.assertTrue(Entity.objects.filter(pk=entity.pk).exists())

    @override_settings(DEBUG=True)
    def test_copy_is_read_only_and_excludes_private_accounts(self):
        if connection.vendor != 'postgresql':
            self.skipTest('PostgreSQL required')
        source = Path(settings.BASE_DIR) / 'db.sqlite3'
        before = hashlib.sha256(source.read_bytes()).hexdigest()
        with patch.object(type(self), 'databases', self.databases | {'sqlite_content_import'}):
            self.command(source=str(source))
            self.assertFalse(Entity.objects.exists())
            self.command(source=str(source), apply=True)
        self.assertEqual(HistoricalEvent.objects.count(), 6)
        self.assertEqual(StoryPassage.objects.count(), 46)
        self.assertEqual(Evidence.objects.count(), 133)
        self.assertFalse(User.objects.exists())
        self.assertFalse(ProviderConfiguration.objects.exists())
        self.assertFalse(Entity.objects.exclude(created_by=None).exists())
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before)
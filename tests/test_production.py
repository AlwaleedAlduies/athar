import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
from contextlib import ExitStack
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DatabaseError
from django.test import TestCase, SimpleTestCase, override_settings

from apps.ai.models import ProviderConfiguration, AIQueryLog
from apps.history.models import Entity, HistoricalEvent, StoryPassage
from apps.history.audit import audit_content


class HealthTests(TestCase):
    def test_readiness_does_not_cache_or_expose_details(self):
        response = self.client.get('/healthz/')
        self.assertEqual(response.json(), {'status': 'ok'})
        self.assertEqual(response['Cache-Control'], 'no-store')
        with patch('config.health.connection.cursor', side_effect=DatabaseError('private connection details')):
            response = self.client.get('/healthz/')
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {'status': 'unavailable'})

    @override_settings(SECURE_SSL_REDIRECT=True, SECURE_REDIRECT_EXEMPT=[r'^healthz/$'],
                       SECURE_PROXY_SSL_HEADER=('HTTP_X_FORWARDED_PROTO', 'https'))
    def test_private_health_and_https_proxy(self):
        self.assertEqual(self.client.get('/healthz/').status_code, 200)
        self.assertEqual(self.client.get('/login/').status_code, 301)
        self.assertEqual(self.client.get('/login/', HTTP_X_FORWARDED_PROTO='https').status_code, 200)


@override_settings(DEMO_MODE=False)
class PublicBootstrapTests(TestCase):
    def test_clean_install_has_reviewed_stories_without_local_private_data(self):
        call_command('bootstrap_public_content', stdout=io.StringIO())
        self.assertEqual(HistoricalEvent.objects.visible().count(), 6)
        self.assertEqual(StoryPassage.objects.filter(status='PUBLISHED').count(), 46)
        self.assertEqual(audit_content()['issues'], [])
        self.assertFalse(get_user_model().objects.exists())
        self.assertFalse(ProviderConfiguration.objects.exists())
        self.assertFalse(AIQueryLog.objects.exists())
        for event in HistoricalEvent.objects.visible():
            self.assertEqual(self.client.get(event.get_absolute_url()).status_code, 200)
        before = Entity.objects.count()
        with self.assertRaisesMessage(CommandError, 'Content already exists'):
            call_command('bootstrap_public_content', stdout=io.StringIO())
        self.assertEqual(Entity.objects.count(), before)

    def test_failed_audit_rolls_back_content(self):
        from apps.history.management.commands import bootstrap_public_content
        real_call = call_command

        def fail_audit(name, **kwargs):
            if name == 'audit_content':
                raise CommandError('Audit failed')
            return real_call(name, **kwargs)

        with patch.object(bootstrap_public_content, 'call_command', side_effect=fail_audit):
            with self.assertRaisesMessage(CommandError, 'Audit failed'):
                call_command('bootstrap_public_content', stdout=io.StringIO())
        self.assertFalse(Entity.objects.exists())


class ProductionSettingsTests(SimpleTestCase):
    def run_check(self, **overrides):
        env = {**os.environ, 'DJANGO_SETTINGS_MODULE': 'config.production', 'DEBUG': 'false',
               'DEMO_MODE': 'false', 'SECRET_KEY': 'test-only-production-validation-key-' * 3,
               'DATABASE_URL': 'postgresql://test:test@localhost:5432/test',
               'ALLOWED_HOSTS': 'athar.example.com,localhost',
               'CSRF_TRUSTED_ORIGINS': 'https://athar.example.com', **overrides}
        return subprocess.run([sys.executable, '-X', 'utf8', 'manage.py', 'check', '--deploy', '--fail-level', 'WARNING'],
                              cwd=Path(__file__).resolve().parent.parent, env=env,
                              capture_output=True, text=True, encoding='utf-8', timeout=30)

    def test_secure_settings_pass_deployment_checks(self):
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_railway_generated_domain_passes_deployment_checks(self):
        result = self.run_check(RAILWAY_PUBLIC_DOMAIN='athar-test.up.railway.app',
                                ALLOWED_HOSTS='', CSRF_TRUSTED_ORIGINS='')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_unsafe_configuration_refused(self):
        for changes, message in [({'DEBUG': 'true'}, 'requires DEBUG=false'),
                                 ({'DEMO_MODE': 'true'}, 'requires DEMO_MODE=false'),
                                 ({'ALLOWED_HOSTS': '*'}, 'explicit ALLOWED_HOSTS'),
                                 ({'CSRF_TRUSTED_ORIGINS': 'http://athar.example.com'}, 'explicit HTTPS'),
                                 ({'DATABASE_URL': 'sqlite:///:memory:'}, 'requires a PostgreSQL'),
                                 ({'SECRET_KEY': 'short'}, 'at least 50 characters')]:
            with self.subTest(changes=changes):
                result = self.run_check(**changes)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stderr)


class RailwayVolumeTests(SimpleTestCase):
    def test_root_mount_is_owned_by_app_before_dropping_privileges(self):
        from deploy.serve import prepare_railway_volume
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, {'RAILWAY_VOLUME_MOUNT_PATH': directory, 'MEDIA_ROOT': directory}))
            stack.enter_context(patch.dict(sys.modules, {'pwd': SimpleNamespace(getpwnam=lambda name: SimpleNamespace(pw_uid=1000, pw_gid=1000))}))
            stack.enter_context(patch('os.geteuid', return_value=0, create=True))
            calls = []
            for name in ('chown', 'setgroups', 'setgid', 'setuid'):
                stack.enter_context(patch('os.' + name, side_effect=lambda *args, label=name: calls.append((label, args)), create=True))
            prepare_railway_volume()
            self.assertEqual(calls, [('chown', (Path(directory).resolve(), 1000, 1000)),
                                     ('setgroups', ([],)), ('setgid', (1000,)), ('setuid', (1000,))])

    def test_mismatched_mount_stops_startup(self):
        from deploy.serve import prepare_railway_volume
        with patch.dict(os.environ, {'RAILWAY_VOLUME_MOUNT_PATH': '/wrong', 'MEDIA_ROOT': '/app/media'}), \
             patch('os.geteuid', return_value=0, create=True), \
             patch.dict(sys.modules, {'pwd': SimpleNamespace(getpwnam=lambda name: SimpleNamespace(pw_uid=1000, pw_gid=1000))}):
            with self.assertRaisesMessage(RuntimeError, 'mounted at MEDIA_ROOT'):
                prepare_railway_volume()

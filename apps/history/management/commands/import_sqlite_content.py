"""Copy public historical content from a protected SQLite file into empty dev PostgreSQL."""
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import tempfile

from django.apps import apps
from django.conf import settings
from django.core import serializers
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connections, transaction


CONTENT_APPS = ('history', 'sources', 'knowledge', 'simulations')


class Command(BaseCommand):
    help = 'Import historical content into empty development PostgreSQL; never copies users or secrets.'

    def add_arguments(self, parser):
        parser.add_argument('--source', default=str(settings.BASE_DIR / 'db.sqlite3'))
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, **options):
        settings_module = os.environ.get('DJANGO_SETTINGS_MODULE', '') or settings.SETTINGS_MODULE or ''
        if not settings.DEBUG or 'production' in settings_module:
            raise CommandError('Development only. Publish initializes the production database.')
        target = connections['default']
        if target.vendor != 'postgresql':
            raise CommandError('Target must be development PostgreSQL. SQLite is never modified.')
        models = [
            model for label in CONTENT_APPS
            for model in apps.get_app_config(label).get_models()
        ]
        if any(model._base_manager.exists() for model in models):
            raise CommandError('Target content already exists; refusing to overwrite it.')
        source = Path(options['source']).resolve()
        if not source.is_file():
            raise CommandError('Source SQLite file does not exist.')
        alias = 'sqlite_content_import'
        config = deepcopy(target.settings_dict)
        config.update(
            ENGINE='django.db.backends.sqlite3',
            NAME=f'{source.as_uri()}?mode=ro',
            USER='', PASSWORD='', HOST='', PORT='',
            OPTIONS={'uri': True},
            CONN_MAX_AGE=0,
        )
        connections.databases[alias] = config
        try:
            records = json.loads(serializers.serialize(
                'json',
                (
                    obj for model in models
                    for obj in model._base_manager.using(alias).order_by('pk').iterator()
                ),
            ))
        finally:
            connections[alias].close()
            del connections[alias]
            connections.databases.pop(alias, None)
        # The content retains its IDs and internal links. Nullable references
        # to local accounts/analysis jobs are cleared, not copied to a public app.
        for record in records:
            model = apps.get_model(record['model'])
            for field in model._meta.local_fields:
                if field.is_relation and field.related_model._meta.app_label not in CONTENT_APPS:
                    if not field.null:
                        raise CommandError(f'Cannot omit required private relation: {field.name}')
                    record['fields'][field.name] = None
        self.stdout.write(f'{len(records)} content records ready; users, sessions and AI settings excluded.')
        if not options['apply']:
            self.stdout.write('Dry run only. Add --apply to import.')
            return
        # PostgreSQL checks all imported foreign keys at the end of loaddata.
        # The surrounding transaction also protects against a partially loaded fixture.
        with tempfile.TemporaryDirectory(prefix='athar-content-') as directory:
            fixture = Path(directory) / 'content.json'
            fixture.write_text(json.dumps(records, ensure_ascii=False), encoding='utf-8')
            with transaction.atomic():
                # Re-check emptiness after acquiring a lock, preventing concurrent imports.
                with target.cursor() as cursor:
                    cursor.execute("SELECT pg_advisory_xact_lock(604102026)")
                if any(model._base_manager.exists() for model in models):
                    raise CommandError('Target content already exists; refusing to overwrite it.')
                call_command('loaddata', str(fixture), stdout=io.StringIO())
                target.check_constraints()
        self.stdout.write(self.style.SUCCESS('Content imported. Original SQLite file was read-only and unchanged.'))
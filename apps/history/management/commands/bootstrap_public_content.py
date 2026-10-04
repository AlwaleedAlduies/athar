"""Install the reviewed public reading packs on a clean production database."""
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from apps.history.models import Entity


class Command(BaseCommand):
    help = 'Install public content only on an empty PostgreSQL database; never copies local users or secrets.'

    def handle(self, *args, **options):
        database = str(connection.settings_dict['NAME'])
        if connection.vendor == 'sqlite' and database != ':memory:' and not database.startswith('file:memory'):
            raise CommandError('Use PostgreSQL for production bootstrap. Persistent local SQLite data is protected.')
        if Entity.objects.exists():
            raise CommandError('Content already exists; preserved. Bootstrap only supports an empty content database.')
        # One transaction: a failed content audit rolls back every imported pack.
        with transaction.atomic():
            for command in ('import_dorar_pilot', 'enrich_medina', 'enrich_stories', 'complete_journey'):
                call_command(command, apply=True, stdout=self.stdout)
            call_command('audit_content', strict=True, stdout=self.stdout)
        self.stdout.write(self.style.SUCCESS('Public content installed. Create the production administrator separately.'))

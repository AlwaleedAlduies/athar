import json
from django.core.management.base import BaseCommand, CommandError
from apps.history.audit import audit_content


class Command(BaseCommand):
    help = 'Audit published narrative depth, evidence, people and place connections without modifying data.'

    def add_arguments(self, parser):
        parser.add_argument('--strict', action='store_true')

    def handle(self, *args, **options):
        report = audit_content()
        self.stdout.write(json.dumps(report, ensure_ascii=False, indent=2))
        if options['strict'] and report['issues']:
            raise CommandError(f'{len(report["issues"])} content issues need review.')

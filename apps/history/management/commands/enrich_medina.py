"""Enrich three existing events with a small, reviewed, reproducible reading pack."""
import json
import sqlite3
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone
from apps.ai.embeddings import HashEmbedding
from apps.dashboard.forms import validate_editorial
from apps.history.models import HistoricalEvent, HistoricalPerson, Status
from apps.knowledge.models import HistoricalClaim, Evidence, EntityRelationship
from apps.sources.models import HistoricalSource, SourceChunk
from .import_dorar_pilot import DATA as PILOT_DATA

DATA = PILOT_DATA.parent / 'medina_focus.json'


def validate_pack(pack, pilot):
    event_slugs = {r['slug'] for r in pack['events']}
    if event_slugs != {'badr', 'uhud', 'khandaq'}:
        raise CommandError('This pack enriches exactly three existing topics.')
    keys, word_counts = {'pilot-khandaq'}, defaultdict(int)
    for row in pilot['events']:
        word_counts[f'dorar-history-{row["external_id"]}'] += len(row['quote'].split())
    for source in pack['sources']:
        url = urlparse(source['url'])
        if url.scheme != 'https' or url.hostname not in {'dorar.net', 'hadeethenc.com'} or url.username or url.password:
            raise CommandError('Unexpected source origin.')
        for excerpt in source['excerpts']:
            if excerpt['key'] in keys or not excerpt['text'].strip():
                raise CommandError('Duplicate or empty excerpt.')
            keys.add(excerpt['key'])
            word_counts[source['slug']] += len(excerpt['text'].split())
    for excerpt in pack['extra_excerpts']:
        if excerpt['key'] in keys or not excerpt['text'].strip():
            raise CommandError('Duplicate or empty excerpt.')
        keys.add(excerpt['key'])
        word_counts[excerpt['source']] += len(excerpt['text'].split())
    if any(count > 25 for count in word_counts.values()):
        raise CommandError('The pack exceeds its bounded excerpt budget.')
    claim_keys = set()
    for row in pack['claims']:
        if row['key'] in claim_keys or row['event'] not in event_slugs or not row['excerpts'] or not set(row['excerpts']) <= keys:
            raise CommandError('Invalid claim reference.')
        claim_keys.add(row['key'])
    for row in pack['event_links']:
        if row['claim'] not in claim_keys or row['from'] not in event_slugs or row['to'] not in event_slugs:
            raise CommandError('Invalid event relationship.')


class Command(BaseCommand):
    help = 'Preview the Badr/Uhud/Khandaq enrichment; use --apply to commit with a backup.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, **options):
        pack = json.loads(DATA.read_text(encoding='utf-8'))
        pilot = json.loads(PILOT_DATA.read_text(encoding='utf-8'))
        validate_pack(pack, pilot)
        marker = pack['batch'] + ':'
        imported = HistoricalClaim.objects.filter(review_notes__startswith=marker).count()
        if imported == len(pack['claims']):
            self.stdout.write('No changes. Existing focus pack and editorial changes preserved.'); return
        if imported or HistoricalSource.objects.filter(slug__in=[s['slug'] for s in pack['sources']]).exists():
            raise CommandError('Partial or conflicting pack; inspect it before continuing.')
        base = {row['slug']: row for row in pilot['events']}
        events = {}
        for row in pack['events']:
            event = HistoricalEvent.objects.visible().filter(slug=row['slug'], is_demo=False).first()
            if not event or not event.sources.filter(slug=f'dorar-history-{base[row["slug"]]["external_id"]}').exists():
                raise CommandError('Run import_dorar_pilot --apply first.')
            for field in row['append']:
                if field not in {'narrative', 'decisions', 'aftermath', 'consequences'} or getattr(event, field) != base[row['slug']][field]:
                    raise CommandError(f'Editorial changes protected: {row["slug"]}/{field}')
            events[row['slug']] = event
        db_name = str(connection.settings_dict['NAME'])
        if options['apply'] and connection.vendor == 'sqlite' and db_name != ':memory:' and not db_name.startswith('file:'):
            backup_dir = Path(settings.BASE_DIR) / 'backups'; backup_dir.mkdir(exist_ok=True)
            backup_path = backup_dir / f'before-medina-{timezone.now():%Y%m%d-%H%M%S-%f}.sqlite3'
            with sqlite3.connect(db_name) as original, sqlite3.connect(backup_path) as backup:
                original.backup(backup)
            self.stdout.write(f'Backup: {backup_path.name}')
        with transaction.atomic():
            excerpts = {'pilot-khandaq': SourceChunk.objects.get(source__slug='dorar-history-84', ordinal=0)}
            for row in pack['sources']:
                source = HistoricalSource(slug=row['slug'], title=row['title'], author=row['author'], url=row['url'],
                    source_type='digital', status=Status.PUBLISHED, is_approved=True, is_demo=False,
                    description=pack['method'], publication_information=row['reference'] + f' الاطلاع: {pack["accessed_on"]}. {pack["batch"]}.', processed_at=timezone.now())
                source.full_clean(); validate_editorial(source); source.save()
                for ordinal, excerpt in enumerate(row['excerpts']):
                    excerpts[excerpt['key']] = self.chunk(source, ordinal, excerpt)
            for excerpt in pack['extra_excerpts']:
                source = HistoricalSource.objects.visible().get(slug=excerpt['source'], is_approved=True)
                last = source.chunks.order_by('-ordinal').first()
                excerpts[excerpt['key']] = self.chunk(source, last.ordinal + 1 if last else 0, excerpt)
            for row in pack['people']:
                person = HistoricalPerson.objects.filter(slug=row['slug']).first()
                if person:
                    if person.status not in [Status.APPROVED, Status.PUBLISHED] or person.deleted_at or person.is_demo:
                        raise CommandError(f'Private person conflicts: {row["slug"]}')
                else:
                    person = HistoricalPerson(**row, era=events['badr'].era, status=Status.PUBLISHED, is_demo=False)
                    person.full_clean(); person.save()
            claims, roles = {}, defaultdict(list)
            for row in pack['claims']:
                event = events[row['event']]
                person = HistoricalPerson.objects.visible().get(slug=row['person']) if row.get('person') else None
                claim = HistoricalClaim.objects.create(event=event, person=person, claim_text=row['text'],
                    claim_type='FACT', status=Status.REVIEW, is_demo=False,
                    review_notes=marker + row['key'] + ' | ' + pack['method'])
                for key in row['excerpts']:
                    chunk = excerpts[key]
                    evidence = Evidence(claim=claim, source=chunk.source, source_chunk=chunk, evidence_text=chunk.text,
                        section=chunk.section, notes='مقتطف حرفي محدود؛ تُقرأ المقتطفات معًا وفي سياق الصفحة. بيانات التخريج في بطاقة المصدر؛ لا رقم صفحة ورقي مفترض.')
                    evidence.full_clean(); evidence.save()
                    event.sources.add(chunk.source)
                claim.status = Status.APPROVED; validate_editorial(claim); claim.save()
                claims[row['key']] = claim
                if person:
                    event.persons.add(person)
                    # Replace only the pilot's generic person link, not user-created links.
                    EntityRelationship.objects.filter(from_entity=person, to_entity=event, relation_type='RELATED_TO',
                        notes__contains=pilot['batch']).update(status=Status.ARCHIVED)
                    self.relate(person, event, row['relation'], claim, row['role'], pilot['batch'])
                    roles[person.pk].append(f'{event.title}: {row["role"]}')
                for source in {excerpts[key].source for key in row['excerpts']}:
                    existing = EntityRelationship.objects.filter(from_entity=event, to_entity=source, relation_type='MENTIONED_IN').first()
                    if not existing or not existing.supporting_claim_id:
                        self.relate(event, source, 'MENTIONED_IN', claim, 'مرجع مستخدم في هذه المحطة؛ الدليل يبين موضع الاستشهاد.', pilot['batch'])
            for row in pack['event_links']:
                start, end = events[row['from']], events[row['to']]
                self.relate(start, end, row['type'], claims[row['claim']], row['note'], pilot['batch'])
                start.related_events.add(end)
            for row in pack['events']:
                event = events[row['slug']]
                for field, extra in row['append'].items():
                    setattr(event, field, getattr(event, field) + '\n\n' + extra)
                event.full_clean(); validate_editorial(event); event.save()
            for pk, descriptions in roles.items():
                person = HistoricalPerson.objects.get(pk=pk)
                if person.created_by_id is None and person.description.startswith('بطاقة ربط'):
                    person.description = '\n\n'.join(descriptions)
                    person.full_clean(); person.save()
            if not options['apply']:
                transaction.set_rollback(True)
        mode = 'APPLIED' if options['apply'] else 'PREVIEW (rolled back)'
        self.stdout.write(self.style.SUCCESS(f'{mode}: 3 events enriched; 0 events added; {len(pack["sources"])} sources, {len(claims)} claims.'))

    def chunk(self, source, ordinal, row):
        chunk = SourceChunk(source=source, ordinal=ordinal, text=row['text'], section=row['section'],
            embedding=HashEmbedding().embed(row['text']), embedding_reference=HashEmbedding.reference)
        chunk.full_clean(); chunk.save()
        return chunk

    def relate(self, start, end, kind, claim, note, pilot_marker):
        edge = EntityRelationship.objects.filter(from_entity=start, to_entity=end, relation_type=kind).first()
        seed_placeholder = edge and edge.status == Status.ARCHIVED and 'تجريبي' in edge.notes
        if edge and pilot_marker not in edge.notes and not seed_placeholder:
            raise CommandError(f'Existing editorial relationship protected: {edge.pk}')
        edge = edge or EntityRelationship(from_entity=start, to_entity=end, relation_type=kind)
        edge.supporting_claim, edge.notes, edge.status = claim, note, Status.PUBLISHED
        edge.full_clean(); validate_editorial(edge); edge.save()

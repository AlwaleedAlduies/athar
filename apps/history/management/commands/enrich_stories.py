"""Install reviewed story paragraphs without replacing existing editorial records."""
import json
import sqlite3
from pathlib import Path
from collections import Counter
from urllib.parse import urlsplit
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.utils import timezone
from apps.ai.embeddings import HashEmbedding
from apps.dashboard.forms import validate_editorial
from apps.history.models import HistoricalEvent, HistoricalPerson, StoryPassage, Status
from apps.history.story import validate_citations, sync_story_references
from apps.knowledge.models import HistoricalClaim, Evidence, EntityRelationship
from apps.sources.models import HistoricalSource, SourceChunk

DATA = Path(settings.BASE_DIR) / 'data' / 'story_readings.json'


class Command(BaseCommand):
    help = 'Preview reviewed stories for three events. --apply backs up SQLite and commits.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, **options):
        pack = json.loads(DATA.read_text(encoding='utf-8'))
        marker = pack['batch'] + ':'
        total = sum(len(e['passages']) for e in pack['events'])
        count = StoryPassage.objects.filter(editorial_key__startswith=marker).count()
        if count == total:
            self.stdout.write('No changes. Story pack and subsequent editorial changes preserved.'); return
        if count or HistoricalSource.objects.filter(slug__in=[r['slug'] for r in pack['sources']]).exists():
            raise CommandError('Partial/conflicting story pack. Inspect before continuing.')
        events = {e.slug: e for e in HistoricalEvent.objects.visible().filter(slug__in=['badr', 'uhud', 'khandaq'], is_demo=False)}
        if len(events) != 3 or not HistoricalSource.objects.filter(slug='dorar-khandaq-work-2834').exists():
            raise CommandError('Apply import_dorar_pilot and enrich_medina first.')
        if any(e.story_passages.exists() for e in events.values()):
            raise CommandError('Existing editor-authored story preserved; import stopped.')
        for row in pack['sources']:
            if urlsplit(row['url']).hostname not in {'dorar.net', 'sunnah.global'} or not row['url'].startswith('https://'):
                raise CommandError('Unreviewed source origin.')
            if sum(len(e['text'].split()) for e in row['excerpts']) > 25:
                raise CommandError('Excerpt budget exceeded.')
        db_name = str(connection.settings_dict['NAME'])
        if options['apply'] and connection.vendor == 'sqlite' and db_name != ':memory:' and not db_name.startswith('file:'):
            folder = Path(settings.BASE_DIR) / 'backups'; folder.mkdir(exist_ok=True)
            target = folder / f'before-stories-{timezone.now():%Y%m%d-%H%M%S-%f}.sqlite3'
            with sqlite3.connect(db_name) as original, sqlite3.connect(target) as backup:
                original.backup(backup)
            self.stdout.write(f'Backup: {target.name}')
        with transaction.atomic():
            engine = HashEmbedding()
            for row in pack['sources']:
                source = HistoricalSource(slug=row['slug'], title=row['title'], author=row['author'], url=row['url'],
                    source_type='digital', status=Status.PUBLISHED, is_approved=True, is_demo=False,
                    description=pack['method'], publication_information=row['reference'] + f' الاطلاع: {pack["accessed_on"]}.', processed_at=timezone.now())
                source.full_clean(); validate_editorial(source); source.save()
                for ordinal, ref in enumerate(row['excerpts']):
                    chunk = SourceChunk(source=source, ordinal=ordinal, **ref, embedding=engine.embed(ref['text']), embedding_reference=engine.reference)
                    chunk.full_clean(); chunk.save()
            for row in pack['people']:
                person, created = HistoricalPerson.objects.get_or_create(slug=row['slug'], defaults={**row,
                    'era': events['badr'].era, 'status': Status.PUBLISHED, 'is_demo': False})
                if not HistoricalPerson.objects.visible().filter(pk=person.pk, is_demo=False).exists():
                    raise CommandError('A private person conflicts with a story participant.')
            for event_row in pack['events']:
                event = events[event_row['slug']]
                for position, row in enumerate(event_row['passages'], start=1):
                    key = f'{marker}{event.slug}:{position}'
                    claim = HistoricalClaim.objects.create(event=event,
                        person=HistoricalPerson.objects.get(slug=row['person']) if row.get('person') else None,
                        claim_text=row['text'], claim_type=row.get('classification', 'INTERPRETATION'),
                        status=Status.REVIEW, review_notes=key + ' | ' + pack['method'])
                    for source_slug, ordinal in row['refs']:
                        chunk = SourceChunk.objects.get(source__slug=source_slug, ordinal=ordinal)
                        proof = Evidence(claim=claim, source=chunk.source, source_chunk=chunk, evidence_text=chunk.text,
                            section=chunk.section, page_number=chunk.page_number, support_type='CONTEXTUALIZES',
                            notes='صياغة سردية تحريرية للسياق، لا اقتباس حرفي. المقتطف علامة على الموضع؛ تفاصيل الفقرة تُراجع في متن الرابط الأصلي، واختلاف الروايات محفوظ في السرد.')
                        proof.full_clean(); proof.save()
                    claim.status = Status.APPROVED; validate_editorial(claim); claim.save()
                    passage = StoryPassage.objects.create(event=event, chapter=row['chapter'], text=row['text'], position=position,
                        status=Status.DRAFT, editorial_key=key)
                    passage.citations.add(claim)
                    passage.status = Status.PUBLISHED; validate_citations(passage, [claim]); passage.save()
                    sync_story_references(passage)
                    if claim.person_id:
                        edge, created = EntityRelationship.objects.get_or_create(from_entity=claim.person, to_entity=event,
                            relation_type='PARTICIPATED_IN', defaults={'supporting_claim': claim, 'notes': row.get('role_note', row['text']), 'status': Status.PUBLISHED})
                        if created:
                            edge.full_clean(); validate_editorial(edge)
                    for source in HistoricalSource.objects.filter(pk__in=claim.evidence.values('source_id')):
                        edge, created = EntityRelationship.objects.get_or_create(from_entity=event, to_entity=source, relation_type='MENTIONED_IN',
                            defaults={'supporting_claim': claim, 'notes': 'من مراجع السرد؛ افتح الاستشهاد لمراجعة السياق.', 'status': Status.PUBLISHED})
                        if created:
                            edge.full_clean(); validate_editorial(edge)
                # Existing long fields remain available to editors; reader and journey prefer cited passages.
                if event.created_by_id is None:
                    event.description = event_row['description']; event.save(update_fields=['description'])
                words = sum(len(r['text'].split()) for r in event_row['passages'])
                self.stdout.write(f'{event.slug}: {len(event_row["passages"])} passages / {words} words')
            if not options['apply']:
                transaction.set_rollback(True)
        self.stdout.write(self.style.SUCCESS(f'{"APPLIED" if options["apply"] else "PREVIEW (rolled back)"}: {total} linked passages; 3 existing topics.'))

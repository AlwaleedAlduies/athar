"""Install a reviewed, bounded extension to the six existing public topics."""
import json
import sqlite3
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.utils import timezone
from apps.ai.embeddings import HashEmbedding
from apps.dashboard.forms import validate_editorial
from apps.history.models import Entity, HistoricalEvent, HistoricalPerson, StoryPassage, Status
from apps.history.story import validate_citations, sync_story_references
from apps.knowledge.models import HistoricalClaim, Evidence, EntityRelationship
from apps.sources.models import HistoricalSource, SourceChunk


DATA = Path(settings.BASE_DIR) / 'data' / 'journey_completion.json'


class Command(BaseCommand):
    help = 'Preview cited stories, roles and connections for existing topics; --apply backs up and saves.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, **options):
        pack = json.loads(DATA.read_text(encoding='utf-8'))
        marker = pack['batch'] + ':'
        expected = sum(len(e['passages']) for e in pack['events'])
        installed = StoryPassage.objects.filter(editorial_key__startswith=marker).count()
        if installed == expected:
            self.stdout.write('Already installed; later editorial changes preserved.')
            return
        if installed or HistoricalClaim.objects.filter(review_notes__startswith=marker).exists():
            raise CommandError('Partial pack: inspect before continuing.')
        event_slugs = {e['slug'] for e in pack['events']}
        events = {e.slug: e for e in HistoricalEvent.objects.visible().filter(slug__in=event_slugs, is_demo=False)}
        if set(events) != event_slugs or any(e.story_passages.exists() for e in events.values()):
            raise CommandError('Public pilot topics are required and existing stories must be preserved.')
        if HistoricalSource.objects.filter(slug__in=[s['slug'] for s in pack['sources']]).exists():
            raise CommandError('A source conflicts with this pack; no records changed.')
        # The import may enrich relationships, but must not replace user-authored event fields.
        pilot = json.loads((DATA.parent / 'dorar_history_pilot.json').read_text(encoding='utf-8'))
        baseline = {r['slug']: r for r in pilot['events']}
        for slug, event in events.items():
            if event.created_by_id or event.description != baseline[slug]['description']:
                raise CommandError(f'Preserving edited event {slug}; review its proposed changes manually.')
        for s in pack['sources']:
            if sum(len(x['text'].split()) for x in s['excerpts']) > 25:
                raise CommandError(f'Excerpt budget exceeded: {s["slug"]}')
        db = str(connection.settings_dict['NAME'])
        if options['apply'] and connection.vendor == 'sqlite' and db != ':memory:' and not db.startswith('file:'):
            folder = Path(settings.BASE_DIR) / 'backups'
            folder.mkdir(exist_ok=True)
            target = folder / f'before-completion-{timezone.now():%Y%m%d-%H%M%S-%f}.sqlite3'
            with sqlite3.connect(db) as original, sqlite3.connect(target) as backup:
                original.backup(backup)
            self.stdout.write(f'Backup: {target.name}')
        with transaction.atomic():
            engine = HashEmbedding()
            for row in pack['sources']:
                source = HistoricalSource(slug=row['slug'], title=row['title'], author=row['author'], url=row['url'],
                    source_type='digital', status=Status.PUBLISHED, is_approved=True, is_demo=False,
                    description=pack['method'], publication_information=row['reference'] + ' الاطلاع: ' + pack['accessed_on'],
                    processed_at=timezone.now())
                source.full_clean(); validate_editorial(source); source.save()
                for ordinal, excerpt in enumerate(row['excerpts']):
                    chunk = SourceChunk(source=source, ordinal=ordinal, **excerpt, embedding=engine.embed(excerpt['text']), embedding_reference=engine.reference)
                    chunk.full_clean(); chunk.save()
            for row in pack['people']:
                person, _ = HistoricalPerson.objects.get_or_create(slug=row['slug'], defaults={**row,
                    'era': events['hijrah'].era, 'status': Status.PUBLISHED, 'is_demo': False})
                if not HistoricalPerson.objects.visible().filter(pk=person.pk, is_demo=False).exists():
                    raise CommandError(f'Private person conflicts: {row["slug"]}')

            def make_claim(event, text, refs, key, person=None, place=None):
                claim = HistoricalClaim.objects.create(event=event, person=person, place=place, claim_text=text,
                    claim_type='INTERPRETATION', status=Status.REVIEW, review_notes=marker + key + ' | ' + pack['method'])
                for source_slug, ordinal in refs:
                    chunk = SourceChunk.objects.get(source__slug=source_slug, ordinal=ordinal)
                    if not HistoricalSource.objects.visible().filter(pk=chunk.source_id, is_approved=True, is_demo=False).exists():
                        raise CommandError(f'Unavailable reference: {source_slug}')
                    proof = Evidence(claim=claim, source=chunk.source, source_chunk=chunk, evidence_text=chunk.text,
                        section=chunk.section, support_type='CONTEXTUALIZES',
                        notes='صياغة تحريرية تستند إلى سياق النص العربي في الرابط. المقتطف علامة على الموضع ولا يمثل وحده جميع تفاصيل السرد.')
                    proof.full_clean(); proof.save()
                    event.sources.add(chunk.source)
                claim.status = Status.APPROVED
                validate_editorial(claim); claim.save()
                return claim

            def connect(origin, target, kind, claim, notes):
                link, created = EntityRelationship.objects.get_or_create(from_entity=origin, to_entity=target,
                    relation_type=kind, defaults={'status': Status.PUBLISHED, 'supporting_claim': claim, 'notes': notes})
                if not created:
                    # Reviewed links and editor notes are never overwritten.
                    if link.supporting_claim_id:
                        return link
                    pilot_link = link.status in [Status.PUBLISHED, Status.APPROVED] and 'dorar-history-pilot-' in link.notes
                    seed_link = link.status == Status.ARCHIVED and 'تجريبي' in link.notes
                    if not (pilot_link or seed_link):
                        raise CommandError(f'Preserving editorial relationship {link.pk}; manual review required.')
                    link.supporting_claim = claim
                    link.notes = notes
                    link.status = Status.PUBLISHED
                link.full_clean(); validate_editorial(link); link.save()
                return link

            for row in pack['events']:
                event = events[row['slug']]
                for position, p in enumerate(row['passages'], 1):
                    key = f'{event.slug}:{position}'
                    claim = make_claim(event, p['text'], p['refs'], key)
                    passage = StoryPassage.objects.create(event=event, chapter=p['chapter'], position=position,
                        text=p['text'], status=Status.DRAFT, editorial_key=marker + key)
                    passage.citations.add(claim)
                    passage.status = Status.PUBLISHED
                    validate_citations(passage, [claim]); passage.save(); sync_story_references(passage)
                    for source in HistoricalSource.objects.filter(pk__in=claim.evidence.values('source_id')):
                        connect(event, source, 'MENTIONED_IN', claim, 'من مراجع السرد؛ افتح الاستشهاد لسياق الفقرة.')
                event.description = row['description']
                fields = ['description']
                if row.get('date_label') and event.hijri_label == 'صفر 1 هـ':
                    event.hijri_label = row['date_label']; fields.append('hijri_label')
                event.save(update_fields=fields)
            for role in pack['roles']:
                event = events[role['event']]
                person = HistoricalPerson.objects.visible().get(slug=role['person'])
                claim = make_claim(event, role['text'], role['refs'], 'role:' + event.slug + ':' + person.slug, person=person)
                event.persons.add(person)
                # Strengthen the pilot's unspecified link instead of duplicating its graph edge.
                old = EntityRelationship.objects.filter(from_entity=person, to_entity=event, relation_type='RELATED_TO',
                    supporting_claim__isnull=True, notes__contains='dorar-history-pilot-').first()
                link = connect(person, event, role.get('relation', 'PARTICIPATED_IN'), claim, role['text'])
                if old and old.pk != link.pk and link.supporting_claim_id == claim.pk:
                    old.status = Status.ARCHIVED; old.save(update_fields=['status'])
            for row in pack['links']:
                event = HistoricalEvent.objects.visible().get(slug=row['event'], is_demo=False)
                target = Entity.objects.visible().get(slug=row['target'])
                place = target.historicalplace if target.kind == 'place' else None
                claim = make_claim(event, row['text'], row['refs'], 'link:' + event.slug + ':' + target.slug, place=place)
                connect(event, target, row['relation'], claim, row['text'])
                if target.kind == 'event': event.related_events.add(target.pk)
                if place: event.places.add(place)
            for slug, text in pack.get('profiles', {}).items():
                person = HistoricalPerson.objects.visible().get(slug=slug)
                if person.created_by_id is None and person.description.startswith('بطاقة ربط'):
                    person.description = text
                    person.save(update_fields=['description'])
            if not options['apply']:
                transaction.set_rollback(True)
        self.stdout.write(self.style.SUCCESS(f'{"APPLIED" if options["apply"] else "PREVIEW (rolled back)"}: {expected} passages; {len(pack["roles"])} roles; no new events.'))

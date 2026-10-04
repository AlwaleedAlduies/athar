"""Import a bounded, editorially prepared dataset, not a website crawler."""
import hashlib
import json
import sqlite3
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone
from apps.history.models import HistoricalEra, HistoricalEvent, HistoricalPerson, HistoricalPlace, Status
from apps.sources.models import HistoricalSource, SourceChunk
from apps.knowledge.models import HistoricalClaim, Evidence, EntityRelationship
from apps.dashboard.forms import validate_editorial
from apps.ai.embeddings import HashEmbedding

DATA = Path(__file__).resolve().parents[4] / 'data' / 'dorar_history_pilot.json'
PEOPLE = {
    'prophet-muhammad': 'النبي محمد ﷺ', 'abu-bakr': 'أبو بكر الصديق',
    'umar-ibn-al-khattab': 'عمر بن الخطاب', 'abu-sufyan': 'أبو سفيان بن حرب',
    'abdullah-ibn-jubayr': 'عبد الله بن جبير', 'khalid-ibn-al-walid': 'خالد بن الوليد',
    'uthman-ibn-affan': 'عثمان بن عفان', 'suhayl-ibn-amr': 'سهيل بن عمرو', 'umm-salama': 'أم سلمة',
}
PLACES = {'makkah': 'مكة المكرمة', 'madinah': 'المدينة المنورة', 'badr-place': 'بدر',
          'hudaybiyyah-place': 'الحديبية', 'thawr': 'غار ثور', 'uhud-place': 'أُحد'}


def validate_dataset(data):
    seen = set()
    for row in data['events']:
        if row['external_id'] in seen or row['url'] != f'https://dorar.net/history/event/{row["external_id"]}':
            raise CommandError('Invalid or duplicate Dorar reference.')
        seen.add(row['external_id'])
        if not row['quote'].strip() or len(row['quote'].split()) > 25:
            raise CommandError('Each source requires a short, bounded supporting excerpt.')
        if row['precision'] not in HistoricalEvent.Precision.values:
            raise CommandError('Invalid date precision.')
        if any(slug not in PEOPLE for slug in row['people']) or any(slug not in PLACES for slug in row['places']):
            raise CommandError('Unknown person or place.')


class Command(BaseCommand):
    help = 'Preview six curated Dorar entries; --apply writes them with evidence and a SQLite backup.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help='Apply the prepared dataset (default is a rollback preview).')

    def reference_entity(self, model, slug, defaults):
        record = model.objects.filter(slug=slug).first()
        if record:
            if record.is_demo and record.created_by_id is None and 'تجريبي' in record.description:
                for field, value in defaults.items():
                    setattr(record, field, value)
                record.full_clean(); record.save()
            elif record.status not in [Status.PUBLISHED, Status.APPROVED] or record.deleted_at:
                raise CommandError(f'Private entity slug conflicts with the import: {slug}')
            return record
        record = model(slug=slug, **defaults)
        record.full_clean(); record.save()
        return record

    def handle(self, *args, **options):
        data = json.loads(DATA.read_text(encoding='utf-8'))
        validate_dataset(data)
        pending, skipped = [], 0
        for row in data['events']:
            event = HistoricalEvent.objects.filter(slug=row['slug']).first()
            source = HistoricalSource.objects.filter(slug=f'dorar-history-{row["external_id"]}').first()
            if source:
                if event and event.sources.filter(pk=source.pk).exists():
                    skipped += 1; continue  # Never overwrite subsequent editorial changes.
                raise CommandError(f'Incomplete or conflicting import: {row["external_id"]}')
            if event and (not event.is_demo or event.created_by_id or 'تجريبي' not in event.narrative):
                raise CommandError(f'Existing editorial event is protected: {row["slug"]}')
            pending.append(row)
        if not pending:
            self.stdout.write(f'No changes. {skipped} existing entries preserved.'); return
        database_name = str(connection.settings_dict['NAME'])
        if options['apply'] and connection.vendor == 'sqlite' and database_name != ':memory:' and not database_name.startswith('file:'):
            backup_dir = Path(settings.BASE_DIR) / 'backups'; backup_dir.mkdir(exist_ok=True)
            backup_path = backup_dir / f'before-dorar-{timezone.now():%Y%m%d-%H%M%S-%f}.sqlite3'
            with sqlite3.connect(connection.settings_dict['NAME']) as original, sqlite3.connect(backup_path) as backup:
                original.backup(backup)
            self.stdout.write(f'Backup: {backup_path.name}')
        with transaction.atomic():
            public = {'status': Status.PUBLISHED, 'is_demo': False}
            era = self.reference_entity(HistoricalEra, 'prophetic-era', {**public, 'title': 'عصر النبوة',
                'start_year': 1, 'end_year': None, 'description': 'باب لتصفح أحداث عصر النبوة. تتناول الدفعة الحالية محطات من السنة الأولى إلى الثامنة للهجرة، اعتمادًا على صفحات الموسوعة التاريخية للدرر السنية.'})
            people, places = {}, {}
            for row in pending:
                for slug in row['people']:
                    if slug not in people:
                        people[slug] = self.reference_entity(HistoricalPerson, slug, {**public, 'title': PEOPLE[slug], 'era': era,
                            'description': 'بطاقة ربط للشخصية الواردة في الأحداث المستوردة من موسوعة الدرر السنية. راجع صفحات الأحداث ومصادرها لمعرفة دورها في كل سياق؛ هذه البطاقة ليست سيرة مستقلة مكتملة.'})
                for slug in row['places']:
                    if slug not in places:
                        places[slug] = self.reference_entity(HistoricalPlace, slug, {**public, 'title': PLACES[slug],
                            'description': 'بطاقة للمكان المذكور في الأحداث المستوردة من موسوعة الدرر السنية. توضح الروابط موضع ذكره؛ لم تُضف إحداثيات أو أوصاف جغرافية غير متحققة.'})
            imported = []
            for row in pending:
                source = HistoricalSource(
                    slug=f'dorar-history-{row["external_id"]}', title='الدرر السنية — ' + row['source_title'],
                    author=data['publisher'], source_type='digital', url=row['url'], **public, is_approved=True,
                    description='صفحة الحدث في الموسوعة التاريخية. المادة في أثَر ملخص تحريري، والمقطع أدناه اقتباس حرفي قصير. الاعتماد هنا لمطابقة المقتطف إلى الصفحة، وليس تحقيقًا مستقلًا لجميع رواياتها.',
                    publication_information=f'مصدر إلكتروني؛ حدث رقم {row["external_id"]}. تاريخ الاطلاع: {data["accessed_on"]}. لا رقم صفحة ورقي. {row["date_note"]} دفعة: {data["batch"]}. بصمة سجل الاستيراد: ' + hashlib.sha256(json.dumps(row, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
                    processed_at=timezone.now())
                source.full_clean(); validate_editorial(source); source.save()
                chunk = SourceChunk.objects.create(source=source, ordinal=0, text=row['quote'], section=row['section'],
                    embedding=HashEmbedding().embed(row['quote']), embedding_reference=HashEmbedding.reference)
                event = HistoricalEvent.objects.filter(slug=row['slug']).first()
                if event:
                    # Archive only the seed's placeholders. Keep real editorial relations and bookmarks.
                    event.claims.filter(is_demo=True).update(status=Status.ARCHIVED)
                    EntityRelationship.objects.filter(Q(from_entity=event) | Q(to_entity=event), notes__contains='تجريبي').update(status=Status.ARCHIVED)
                    event.persons.remove(*event.persons.filter(slug__in=['prophet-muhammad', 'abu-bakr', 'umar-ibn-al-khattab']))
                    event.places.remove(*event.places.filter(slug__in=['makkah', 'madinah', 'badr-place', 'hudaybiyyah-place']))
                    event.sources.remove(*event.sources.filter(is_demo=True))
                else:
                    event = HistoricalEvent(slug=row['slug'])
                event.title, event.era, event.location = row['title'], era, places[row['location']]
                event.is_demo, event.status = False, Status.REVIEW
                event.hijri_label = f'{row["month"]} {row["year"]} هـ' + (' — خلاف في السنة' if row['precision'] == 'approximate' else '')
                event.gregorian_label, event.year_order = row['gregorian'], row['year']
                event.date_precision, event.event_type = row['precision'], row['type']
                for field in ['description', 'narrative', 'context', 'causes', 'decisions', 'consequences', 'aftermath']:
                    setattr(event, field, row[field])
                event.full_clean(); event.save()
                event.sources.add(source)
                event.persons.add(*(people[s] for s in row['people']))
                event.places.add(*(places[s] for s in row['places']))
                claim = HistoricalClaim.objects.create(event=event, claim_text=row['claim'], claim_type=row['claim_type'], status=Status.REVIEW,
                    review_notes=f'مطابقة مقتطف إلى صفحة الدرر بتاريخ {data["accessed_on"]}؛ لم تُراجع الأصول استقلالًا. {data["batch"]}.', is_demo=False)
                evidence = Evidence(claim=claim, source=source, source_chunk=chunk, evidence_text=row['quote'], section=row['section'],
                    notes='اقتباس حرفي قصير من الصفحة الإلكترونية، دون إسناد رقم صفحة ورقي أو ادعاء مراجعة الكتب الأصلية.')
                evidence.full_clean(); evidence.save()
                claim.status = Status.APPROVED; validate_editorial(claim); claim.save()
                event.status = Status.PUBLISHED; validate_editorial(event); event.save()
                def relate(start, end, kind):
                    edge, created = EntityRelationship.objects.get_or_create(from_entity=start, to_entity=end, relation_type=kind,
                        defaults={'status': Status.PUBLISHED, 'notes': f'مذكور في {row["url"]}؛ {data["batch"]}.'})
                    if not created and 'تجريبي' in edge.notes:
                        edge.status = Status.PUBLISHED; edge.notes = f'مذكور في {row["url"]}؛ {data["batch"]}.'; edge.save()
                relate(event, source, 'MENTIONED_IN'); relate(event, era, 'RELATED_TO')
                relate(event, event.location, 'OCCURRED_AT')
                for person_slug in row['people']:
                    relate(people[person_slug], event, 'RELATED_TO')
                for place_slug in row['places']:
                    if places[place_slug] != event.location:
                        relate(event, places[place_slug], 'RELATED_TO')
                imported.append(event)
            placeholder = HistoricalSource.objects.filter(slug='source-review-placeholder', is_demo=True).first()
            if placeholder and not placeholder.events.exists():
                placeholder.status = Status.ARCHIVED; placeholder.save(update_fields=['status'])
            if not options['apply']:
                transaction.set_rollback(True)
        mode = 'APPLIED' if options['apply'] else 'PREVIEW (rolled back)'
        self.stdout.write(self.style.SUCCESS(f'{mode}: {len(imported)} events, {len(imported)} sources, {len(imported)} claims, {len(imported)} evidence records; {skipped} existing entries preserved.'))

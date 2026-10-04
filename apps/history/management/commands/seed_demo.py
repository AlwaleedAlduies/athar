from django.core.management.base import BaseCommand
from django.db import transaction
from apps.history.models import HistoricalEra, HistoricalEvent, HistoricalPerson, HistoricalPlace, Status
from apps.sources.models import HistoricalSource
from apps.knowledge.models import HistoricalClaim, EntityRelationship
from apps.simulations.models import SimulationScenario

DEMO = 'محتوى تاريخي تجريبي — يحتاج مراجعة المصدر.'

class Command(BaseCommand):
    help = 'Seed clearly labeled, non-authoritative demo experiences; never creates credentials or approved RAG sources.'

    @transaction.atomic
    def handle(self, *args, **options):
        base = {'status': Status.PUBLISHED, 'is_demo': True}
        era, _ = HistoricalEra.objects.get_or_create(slug='prophetic-era', defaults={**base, 'title': 'عصر النبوة', 'description': DEMO + ' باب لاستكشاف بدايات التاريخ الإسلامي.', 'start_year': 1, 'end_year': 11})
        places = {}
        for slug, title, desc in [('makkah', 'مكة المكرمة', 'صفحة المكان وما يتصل به من أحداث.'), ('madinah', 'المدينة المنورة', 'مسار للتعرف على المكان وتحولاته.'), ('badr-place', 'بدر', 'مكان يربط المشهد بالحدث.'), ('hudaybiyyah-place', 'الحديبية', 'باب لاستكشاف جغرافية الحدث دون افتراض إحداثيات غير موثقة.')]:
            places[slug], _ = HistoricalPlace.objects.get_or_create(slug=slug, defaults={**base, 'title': title, 'description': DEMO + ' ' + desc})
        people = []
        for slug, title in [('prophet-muhammad', 'النبي محمد ﷺ'), ('abu-bakr', 'أبو بكر الصديق'), ('umar-ibn-al-khattab', 'عمر بن الخطاب')]:
            person, _ = HistoricalPerson.objects.get_or_create(slug=slug, defaults={**base, 'title': title, 'era': era, 'description': DEMO + ' تُستكمل السيرة من مصادر معتمدة قبل النشر العلمي. لا تتضمن هذه الصفحة أقوالًا منسوبة أو حوارًا متخيّلًا.'})
            people.append(person)
        source, _ = HistoricalSource.objects.get_or_create(slug='source-review-placeholder', defaults={**base, 'title': 'مساحة المصدر — بانتظار التوثيق', 'source_type': 'other', 'description': 'مثال يوضح مكان المصدر في رحلة المعرفة. ليس كتابًا ولا مرجعًا تاريخيًا، ولا يُستخدم في استرجاع الإجابات.', 'is_approved': False})
        entries = [
            ('hijrah', 'الهجرة', 1, '622 م', 'journey', 'madinah', 'من المكان إلى التحوّل', 'تأمل كيف يساعد ربط الأشخاص بالأماكن في فهم التحولات. هذه تجربة عرض، وليست سردًا تاريخيًا محققًا.'),
            ('badr', 'غزوة بدر', 2, '624 م', 'battle', 'badr-place', 'قراءة الحدث في سياقه', 'ابدأ بالسياق، ثم انتقل إلى الأطراف والقرارات والنتائج. تنتظر هذه التجربة مراجعة النصوص التاريخية.'),
            ('hudaybiyyah', 'صلح الحديبية', 6, '628 م', 'treaty', 'hudaybiyyah-place', 'حين يستحق القرار وقفة', 'ما الذي قاد إلى هذا الحدث؟ وما الذي ترتب عليه؟ افتح خيوط المشهد، ثم تتبّع ما يدعمه من أدلة بعد اعتمادها.'),
        ]
        events = []
        for slug, title, year, gregorian, event_type, place, subtitle, intro in entries:
            event, created = HistoricalEvent.objects.get_or_create(slug=slug, defaults={**base, 'title': title, 'description': intro,
                'era': era, 'location': places[place], 'hijri_label': f'{year} هـ', 'gregorian_label': gregorian,
                'year_order': year, 'date_precision': 'year', 'event_type': event_type,
                'narrative': DEMO + '\n' + subtitle + '.\nيُظهر هذا المشهد كيف تتصل الرواية بالأشخاص والمكان والدليل. يضيف أمين المعرفة النص المحقق هنا، مع تفكيكه إلى ادعاءات قابلة للتتبع.',
                'context': DEMO + '\nالسياق أكثر من قائمة تواريخ. يكتمل هذا القسم عندما تُربط الوقائع السابقة بمصادرها المعتمدة.',
                'causes': 'لم تُضف أسباب محققة بعد. يراجع أمين المعرفة الأدلة قبل عرض تفسير سببي.',
                'decisions': 'تُضاف القرارات كما وردت في المصادر، مع الفصل بين الرواية والتفسير.',
                'consequences': 'تنتظر النتائج التاريخية توثيقًا. لا يُستنتج أثر قطعي من مجرد تتابع الأحداث.',
                'aftermath': 'تابع روابط الأحداث لاستكشاف ترتيب العرض، مع بقاء المحتوى التجريبي غير معتمد علميًا.'})
            if not event.is_demo:
                events.append(event)
                continue
            if created:
                event.persons.add(people[0], people[1] if slug == 'hijrah' else people[2])
                event.places.add(places[place], places['makkah'])
                event.sources.add(source)
            claim, _ = HistoricalClaim.objects.get_or_create(event=event, is_demo=True, defaults={
                'claim_text': 'مثال تعليمي: كيف نربط أهمية الحدث بدليل من مصدر؟', 'claim_type': 'UNCERTAIN', 'status': Status.PUBLISHED,
                'review_notes': 'هذا مثال على واجهة التتبع، لا ادعاء تاريخي معتمد. أضف ادعاءً حقيقيًا وأدلته بعد مراجعة المصدر.'})
            for target, relation in [(places[place], 'OCCURRED_AT'), (era, 'RELATED_TO'), (source, 'MENTIONED_IN')]:
                EntityRelationship.objects.get_or_create(from_entity=event, to_entity=target, relation_type=relation, defaults={'status': Status.PUBLISHED, 'notes': DEMO})
            for person in event.persons.all():
                EntityRelationship.objects.get_or_create(from_entity=person, to_entity=event, relation_type='PARTICIPATED_IN', defaults={'status': Status.PUBLISHED, 'notes': DEMO})
            events.append(event)
        for first, second in zip(events, events[1:]):
            if not first.is_demo or not second.is_demo:
                continue
            first.related_events.add(second)
            EntityRelationship.objects.get_or_create(from_entity=first, to_entity=second, relation_type='FOLLOWED_BY', defaults={'status': Status.PUBLISHED, 'notes': 'تتابع زمني تجريبي، وليس علاقة سببية.'})
        if events[-1].is_demo:
            SimulationScenario.objects.get_or_create(event=events[-1], title='ماذا لو تغيّر مسار التفاوض؟', defaults={
            'decision_point': 'نشاط في التفكير السببي: كيف تقارن بين الاستمرار في التفاوض وتأجيله؟ لا ينسب هذا النشاط قرارًا جديدًا إلى أي شخصية تاريخية.',
            'alternative': 'تخيل في موقف تعليمي عام أن الأطراف تختار إرجاء الاتفاق، ثم تحدد ما يلزمها للعودة إلى التفاوض.',
            'possible_consequences': 'قد يتيح التأجيل وقتًا لجمع المعلومات، وقد يرفع كلفة الانتظار. لا يمكن الجزم بنتيجة واحدة؛ هذه احتمالات تعليمية وليست رواية تاريخية.',
            'influencing_factors': 'المعلومات المتاحة، الوقت، الموارد، والقدرة على التواصل. دوّن أي افتراض يتغير عندما تتغير هذه العوامل.', 'status': Status.PUBLISHED})
        self.stdout.write(self.style.SUCCESS('Seeded 3 labeled demo experiences. No authoritative sources or credentials were created.'))

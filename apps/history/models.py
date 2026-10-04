from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models


class Status(models.TextChoices):
    DRAFT = 'DRAFT', 'مسودة'
    REVIEW = 'REVIEW', 'قيد المراجعة'
    APPROVED = 'APPROVED', 'معتمد'
    PUBLISHED = 'PUBLISHED', 'منشور'
    ARCHIVED = 'ARCHIVED', 'مؤرشف'
    REJECTED = 'REJECTED', 'مرفوض'


class EntityQuerySet(models.QuerySet):
    def visible(self):
        query = self.filter(status__in=[Status.APPROVED, Status.PUBLISHED], deleted_at__isnull=True)
        return query if settings.DEMO_MODE else query.filter(is_demo=False)


class Entity(models.Model):
    class Kind(models.TextChoices):
        EVENT = 'event', 'حدث'
        PERSON = 'person', 'شخصية'
        PLACE = 'place', 'مكان'
        SOURCE = 'source', 'مصدر'
        ERA = 'era', 'حقبة'
    title = models.CharField('العنوان', max_length=240, db_index=True)
    slug = models.SlugField('الرابط المختصر', max_length=240, unique=True, allow_unicode=True)
    kind = models.CharField(max_length=10, choices=Kind.choices, editable=False)
    description = models.TextField('بين يديك المشهد', blank=True)
    status = models.CharField('حالة النشر', max_length=12, choices=Status.choices, default=Status.DRAFT, db_index=True)
    is_demo = models.BooleanField('محتوى تجريبي يحتاج مراجعة', default=False)
    ai_suggested = models.BooleanField('اقتراح ذكاء اصطناعي', default=False)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='reviewed_entities', editable=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='created_entities', editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True, editable=False)
    objects = EntityQuerySet.as_manager()

    class Meta:
        ordering = ['title']

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return f'/explore/{self.pk}/'

    def save(self, *args, **kwargs):
        kind_map = {'HistoricalEvent': 'event', 'HistoricalPerson': 'person', 'HistoricalPlace': 'place', 'HistoricalEra': 'era', 'HistoricalSource': 'source'}
        self.kind = kind_map.get(type(self).__name__, self.kind)
        super().save(*args, **kwargs)


class HistoricalEra(Entity):
    start_year = models.IntegerField('بداية الحقبة هـ', null=True, blank=True)
    end_year = models.IntegerField('نهاية الحقبة هـ', null=True, blank=True)


class HistoricalPlace(Entity):
    historical_name = models.CharField('الاسم التاريخي', max_length=240, blank=True)
    modern_name = models.CharField('الاسم الحديث', max_length=240, blank=True)
    latitude = models.FloatField('خط العرض الموثق', null=True, blank=True, validators=[MinValueValidator(-90), MaxValueValidator(90)])
    longitude = models.FloatField('خط الطول الموثق', null=True, blank=True, validators=[MinValueValidator(-180), MaxValueValidator(180)])
    significance = models.TextField('الأهمية التاريخية', blank=True)


class HistoricalPerson(Entity):
    alternative_names = models.CharField('أسماء أخرى', max_length=500, blank=True)
    birth_label = models.CharField('الميلاد إن عُرف', max_length=100, blank=True)
    death_label = models.CharField('الوفاة إن عُرفت', max_length=100, blank=True)
    era = models.ForeignKey(HistoricalEra, verbose_name='الحقبة', null=True, blank=True, on_delete=models.SET_NULL, related_name='persons')


class HistoricalEvent(Entity):
    class Precision(models.TextChoices):
        EXACT = 'exact', 'تاريخ محدد'
        YEAR = 'year', 'السنة فقط'
        MONTH = 'month', 'الشهر والسنة'
        APPROXIMATE = 'approximate', 'تقريبي'
        UNKNOWN = 'unknown', 'غير محدد'
    class EventType(models.TextChoices):
        JOURNEY = 'journey', 'رحلة وتحول'
        BATTLE = 'battle', 'معركة'
        TREATY = 'treaty', 'عهد وصلح'
        CULTURE = 'culture', 'علم وحضارة'
    english_title = models.CharField('العنوان الإنجليزي', max_length=240, blank=True)
    narrative = models.TextField('ماذا حدث؟', blank=True)
    hijri_label = models.CharField('التاريخ الهجري', max_length=100, blank=True)
    gregorian_label = models.CharField('التاريخ الميلادي', max_length=100, blank=True)
    year_order = models.IntegerField('سنة الترتيب هـ', null=True, blank=True, db_index=True)
    date_precision = models.CharField('دقة التاريخ', max_length=15, choices=Precision.choices, default=Precision.UNKNOWN)
    era = models.ForeignKey(HistoricalEra, verbose_name='الحقبة', on_delete=models.PROTECT, related_name='events')
    location = models.ForeignKey(HistoricalPlace, verbose_name='المكان', on_delete=models.SET_NULL, null=True, blank=True, related_name='events')
    event_type = models.CharField('نوع الحدث', max_length=15, choices=EventType.choices, default=EventType.JOURNEY)
    context = models.TextField('ما الذي سبق الحدث؟', blank=True)
    causes = models.TextField('الأسباب', blank=True)
    decisions = models.TextField('القرارات', blank=True)
    consequences = models.TextField('النتائج', blank=True)
    aftermath = models.TextField('ما الذي حدث بعد ذلك؟', blank=True)
    persons = models.ManyToManyField(HistoricalPerson, verbose_name='الشخصيات', blank=True, related_name='events')
    places = models.ManyToManyField(HistoricalPlace, verbose_name='الأماكن المرتبطة', blank=True, related_name='related_events')
    sources = models.ManyToManyField('sources.HistoricalSource', verbose_name='المصادر', blank=True, related_name='events')
    related_events = models.ManyToManyField('self', verbose_name='الأحداث المرتبطة', blank=True)
    featured_image = models.URLField('رابط الصورة HTTPS', blank=True)

    class Meta:
        ordering = ['year_order', 'id']


class StoryPassage(models.Model):
    event = models.ForeignKey(HistoricalEvent, verbose_name='الحدث', on_delete=models.CASCADE, related_name='story_passages')
    chapter = models.CharField('عنوان الفصل', max_length=180)
    position = models.PositiveIntegerField('ترتيب الفقرة', default=0)
    text = models.TextField('النص القصصي')
    citations = models.ManyToManyField('knowledge.HistoricalClaim', verbose_name='المعلومات والأدلة الداعمة', related_name='story_passages')
    status = models.CharField('حالة النشر', max_length=12, choices=Status.choices, default=Status.DRAFT)
    editorial_key = models.CharField(max_length=160, blank=True, unique=True, null=True, editable=False)
    ai_suggested = models.BooleanField('اقتراح ذكاء اصطناعي', default=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['position', 'pk']

    def __str__(self):
        return f'{self.event} · {self.chapter} · {self.position}'

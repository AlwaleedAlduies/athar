from django import forms
from django.core.exceptions import ValidationError
from apps.history.models import HistoricalEra, HistoricalEvent, HistoricalPerson, HistoricalPlace, StoryPassage, Status
from apps.sources.models import HistoricalSource, SourceMention, SourceChunk
from apps.knowledge.models import HistoricalClaim, Evidence, EntityRelationship
from apps.simulations.models import SimulationScenario
from .models import SystemSetting

REGISTRY = {
    'mentions': (SourceMention, 'روابط ذكر المصادر'),
    'passages': (StoryPassage, 'فقرات السرد'),
    'events': (HistoricalEvent, 'الأحداث'), 'persons': (HistoricalPerson, 'الشخصيات'),
    'places': (HistoricalPlace, 'الأماكن'), 'eras': (HistoricalEra, 'العصور'),
    'sources': (HistoricalSource, 'المصادر'), 'claims': (HistoricalClaim, 'الادعاءات'),
    'chunks': (SourceChunk, 'مقاطع المصادر'),
    'evidence': (Evidence, 'الأدلة'), 'relationships': (EntityRelationship, 'العلاقات'),
    'simulations': (SimulationScenario, 'المحاكاة'), 'settings': (SystemSetting, 'الإعدادات'),
}

def validate_editorial(instance, citations=None):
    approved = getattr(instance, 'status', None) in [Status.APPROVED, Status.PUBLISHED]
    if isinstance(instance, StoryPassage) and approved:
        from apps.history.story import validate_citations
        if not instance.pk and citations is None:
            raise ValidationError('احفظ الفقرة كمسودة واربط أدلتها قبل النشر.')
        validate_citations(instance, citations if citations is not None else instance.citations.all())
    if isinstance(instance, EntityRelationship) and approved and instance.supporting_claim_id:
        from apps.knowledge.selectors import approved_evidence
        if not approved_evidence().filter(claim_id=instance.supporting_claim_id).exists():
            raise ValidationError('اعتماد الرابطة يتطلب ادعاء منشورًا بدليل من مصدر معتمد.')
    if isinstance(instance, HistoricalClaim) and approved and not instance.is_demo:
        from apps.knowledge.selectors import approved_evidence
        evidence = Evidence.objects.filter(claim_id=instance.pk, source__is_approved=True, source__is_demo=False,
                                          source__status__in=[Status.APPROVED, Status.PUBLISHED], source__deleted_at__isnull=True)
        if not evidence.exists():
            raise ValidationError('أضف دليلًا من مصدر معتمد قبل اعتماد الادعاء.')
        if instance.claim_type == 'FACT' and (not evidence.filter(support_type='SUPPORTS').exists() or evidence.filter(support_type='CONTRADICTS').exists()):
            raise ValidationError('الحقيقة الموثقة تحتاج إلى دليل مباشر دون دليل معارض غير محسوم؛ استخدم اختلاف روايات عند التعارض.')
    if isinstance(instance, HistoricalEvent) and instance.status == Status.PUBLISHED and not instance.is_demo:
        if not instance.pk or not instance.claims.filter(status__in=[Status.APPROVED, Status.PUBLISHED], is_demo=False).exists():
            raise ValidationError('اربط الحدث بادعاء معتمد وأدلته قبل النشر.')
    if isinstance(instance, HistoricalSource) and instance.is_approved:
        if instance.is_demo or instance.status not in [Status.APPROVED, Status.PUBLISHED]:
            raise ValidationError('اعتماد الاسترجاع يتطلب مصدرًا غير تجريبي بحالة معتمد أو منشور.')
    if isinstance(instance, SystemSetting) and instance.key not in {'library_notice', 'welcome_message'}:
        raise ValidationError('المفاتيح المسموحة: library_notice أو welcome_message. تدار الأسرار عبر البيئة فقط.')

class EditorialForm(forms.ModelForm):
    def clean(self):
        data = super().clean()
        if isinstance(self.instance, SourceChunk) and self.instance.pk:
            used = Evidence.objects.filter(source_chunk=self.instance).exists() or self.instance.mentions.exists()
            if used and any(data.get(key) != getattr(self.instance, key) for key in ['source', 'text', 'page_number', 'section', 'ordinal']):
                raise ValidationError('هذا المقطع مستخدم في استشهادات محفوظة. أضف مقطعًا جديدًا وصحح روابط الأدلة قبل إزالة القديم؛ لا يُستبدل النص خلف استشهاد قائم.')
        if isinstance(self.instance, HistoricalSource) and data.get('is_approved') and data.get('status') in [Status.DRAFT,Status.REVIEW]:
            data['status'] = Status.APPROVED
        if isinstance(self.instance, StoryPassage) and data.get('event'):
            from apps.history.story import validate_citations
            self.instance.event, self.instance.status = data['event'], data.get('status', Status.DRAFT)
            validate_citations(self.instance, data.get('citations', []))
        return data
    def clean_slug(self):
        value = self.cleaned_data.get('slug')
        if value:
            return value
        from django.utils.text import slugify
        from uuid import uuid4
        return (slugify(self.cleaned_data.get('title', ''), allow_unicode=True)[:210] or 'content') + '-' + uuid4().hex[:8]
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if 'slug' in self.fields:
            self.fields['slug'].required = False
            self.fields['slug'].help_text = 'اختياري؛ يُنشأ تلقائيًا من العنوان إن تركته فارغًا.'
        def chosen(name):
            value = self.data.get(name) if self.is_bound else self.initial.get(name, getattr(self.instance, name + '_id', None))
            return str(getattr(value, 'pk', value) or '')
        if isinstance(self.instance, StoryPassage):
            event_id = chosen('event')
            if event_id.isdigit():
                self.fields['citations'].queryset = HistoricalClaim.objects.filter(event_id=event_id)
            self.fields['text'].widget.attrs['rows'] = 10
            self.fields['chapter'].help_text = 'الفقرات ذات عنوان الفصل نفسه تُجمع معًا. رتّبها بالأرقام في حقل ترتيب الفقرة.'
        if isinstance(self.instance, (Evidence, SourceMention)):
            source_id = chosen('source')
            key = 'source_chunk' if isinstance(self.instance, Evidence) else 'chunk'
            if source_id.isdigit():
                self.fields[key].queryset = SourceChunk.objects.filter(source_id=source_id)
            self.fields[key].help_text = 'اختر المقطع المطابق للمصدر. يمكنك إنشاء مقطع من صفحة المصدر، ثم العودة لإضافة الدليل.'
        if isinstance(self.instance, SourceChunk):
            self.fields['source'].label = 'المصدر'
            self.fields['ordinal'].label = 'ترتيب المقطع داخل المصدر'
            self.fields['text'].widget.attrs['rows'] = 10
        if isinstance(self.instance, HistoricalSource):
            self.fields['is_approved'].help_text = 'تفعيل هذا الخيار يعتمد المصدر ويغير حالة المسودة إلى «معتمد». المعالجة تجهز النص للاسترجاع.'
        if isinstance(self.instance, SourceMention):
            self.fields['entity'].queryset = self.fields['entity'].queryset.filter(kind__in=['event','person','place','era'],deleted_at__isnull=True,is_demo=False)
        for field in self.fields.values():
            if isinstance(field.widget, forms.Textarea):
                field.widget.attrs.setdefault('rows', 4)
            if isinstance(field, forms.ModelMultipleChoiceField):
                field.widget = forms.CheckboxSelectMultiple()
                field.widget.choices = field.choices
                field.help_text = 'حدد العناصر المطلوبة. استخدم البحث لتضييق الخيارات؛ الاختيارات المخفية تبقى محفوظة.'
            if isinstance(field, (forms.ModelChoiceField, forms.ModelMultipleChoiceField)) and field.queryset.model == HistoricalClaim:
                field.label_from_instance = lambda obj: f'{obj.event.title} · {obj.claim_text[:100]}'
    def _post_clean(self):
        super()._post_clean()
        if not self.errors:
            try:
                validate_editorial(self.instance, self.cleaned_data.get('citations') if isinstance(self.instance, StoryPassage) else None)
            except ValidationError as error:
                self.add_error(None, error)
    def clean_file(self):
        file = self.cleaned_data.get('file')
        if self.instance.pk and file != self.instance.file and self.instance.chunks.exists():
            raise ValidationError('للمصدر مقاطع محفوظة. أنشئ مصدرًا جديدًا للإصدار الجديد حفاظًا على الاستشهادات.')
        return file

def editor_form(model):
    if model == SourceChunk:
        return forms.modelform_factory(model, form=EditorialForm, fields=['source', 'ordinal', 'section', 'page_number', 'text'])
    return forms.modelform_factory(model, form=EditorialForm, exclude=['kind', 'created_by', 'reviewed_by', 'approved_by', 'deleted_at', 'processed_at', 'analysis'])

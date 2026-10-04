from django.db import models
from apps.history.models import Entity, Status
from .validators import validate_document


class HistoricalSource(Entity):
    replaces = models.ForeignKey('self', null=True, blank=True, on_delete=models.PROTECT, related_name='revisions', verbose_name='إصدار سابق للمصدر', editable=False)
    author = models.CharField('المؤلف', max_length=240, blank=True)
    source_type = models.CharField('نوع المصدر', max_length=20, choices=[('book', 'كتاب'), ('article', 'مقال'), ('manuscript', 'مخطوط'), ('research', 'بحث'), ('digital', 'مصدر رقمي'), ('other', 'غير ذلك')], default='book')
    publication_information = models.TextField('بيانات الطبعة والنشر', blank=True)
    language = models.CharField('اللغة', max_length=50, default='العربية')
    url = models.URLField('رابط المصدر', max_length=2048, blank=True)
    file = models.FileField('ملف المصدر', upload_to='sources/%Y/%m/', blank=True, validators=[validate_document])
    is_approved = models.BooleanField('مصدر معتمد للاسترجاع', default=False, db_index=True)
    processed_at = models.DateTimeField(null=True, blank=True, editable=False)


class SourceChunk(models.Model):
    source = models.ForeignKey(HistoricalSource, on_delete=models.CASCADE, related_name='chunks')
    page_number = models.PositiveIntegerField('رقم الصفحة', null=True, blank=True)
    section = models.CharField('الموضع / القسم', max_length=240, blank=True)
    ordinal = models.PositiveIntegerField(default=0)
    text = models.TextField('نص المقطع')
    embedding = models.JSONField(default=list)
    embedding_reference = models.CharField(max_length=160)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['source_id', 'ordinal']
        constraints = [models.UniqueConstraint(fields=['source', 'ordinal'], name='unique_source_ordinal')]

    def __str__(self):
        return f'{self.source.title} — {self.section or self.ordinal}'


class SourceMention(models.Model):
    source = models.ForeignKey(HistoricalSource, on_delete=models.PROTECT, related_name='mentions', verbose_name='المصدر')
    entity = models.ForeignKey(Entity, on_delete=models.PROTECT, related_name='source_mentions', verbose_name='الحدث أو الشخصية أو المكان')
    chunk = models.ForeignKey(SourceChunk, on_delete=models.PROTECT, related_name='mentions', verbose_name='المقطع')
    quote = models.TextField('المقتطف الحرفي')
    context = models.TextField('سياق الذكر', blank=True)
    status = models.CharField('حالة المراجعة', max_length=12, choices=Status.choices, default=Status.DRAFT)
    analysis = models.ForeignKey('dashboard.SourceAnalysis', null=True, blank=True, on_delete=models.SET_NULL)
    reviewed_by = models.ForeignKey('accounts.User', null=True, on_delete=models.SET_NULL, editable=False)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['source','entity','chunk'], name='unique_source_entity_chunk')]

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.chunk_id and (self.chunk.source_id != self.source_id or not self.quote.strip() or self.quote not in self.chunk.text):
            raise ValidationError('موضع الذكر يجب أن يطابق المصدر والمقتطف الحرفي.')
        if self.entity_id and self.entity.kind not in ['event','person','place','era']:
            raise ValidationError('نوع الكيان غير صالح لربط الذكر.')

    def __str__(self):
        return f'{self.entity} · {self.source}'

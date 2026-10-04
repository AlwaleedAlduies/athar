from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from apps.history.models import Status


class HistoricalClaim(models.Model):
    claim_text = models.TextField('الادعاء')
    claim_type = models.CharField('التصنيف', max_length=20, choices=[('FACT', 'حقيقة موثقة'), ('INTERPRETATION', 'تفسير'), ('MULTIPLE_ACCOUNTS', 'اختلاف روايات'), ('UNCERTAIN', 'غير محسوم')], default='UNCERTAIN')
    event = models.ForeignKey('history.HistoricalEvent', verbose_name='الحدث', on_delete=models.CASCADE, related_name='claims')
    person = models.ForeignKey('history.HistoricalPerson', verbose_name='الشخصية', null=True, blank=True, on_delete=models.SET_NULL)
    place = models.ForeignKey('history.HistoricalPlace', verbose_name='المكان', null=True, blank=True, on_delete=models.SET_NULL)
    status = models.CharField('حالة المراجعة', max_length=12, choices=Status.choices, default=Status.DRAFT, db_index=True)
    review_notes = models.TextField('ملاحظات المراجعة', blank=True)
    is_demo = models.BooleanField('مثال تجريبي', default=False)
    ai_suggested = models.BooleanField('اقتراح ذكاء اصطناعي', default=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='claims_created', editable=False)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='claims_approved', editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.claim_text[:90]


class Evidence(models.Model):
    claim = models.ForeignKey(HistoricalClaim, verbose_name='الادعاء', on_delete=models.CASCADE, related_name='evidence')
    source = models.ForeignKey('sources.HistoricalSource', verbose_name='المصدر', on_delete=models.PROTECT)
    source_chunk = models.ForeignKey('sources.SourceChunk', verbose_name='المقطع', null=True, blank=True, on_delete=models.PROTECT)
    evidence_text = models.TextField('نص الدليل')
    page_number = models.PositiveIntegerField('رقم الصفحة', null=True, blank=True)
    section = models.CharField('موضع الدليل', max_length=240, blank=True)
    support_type = models.CharField('نوع الدعم', max_length=20, choices=[('SUPPORTS', 'يدعم'), ('PARTIALLY_SUPPORTS', 'يدعم جزئيًا'), ('CONTRADICTS', 'يعارض'), ('CONTEXTUALIZES', 'يقدم سياقًا')], default='SUPPORTS')
    notes = models.TextField('السياق والملاحظات', blank=True)

    def clean(self):
        if self.source_chunk_id:
            if self.source_chunk.source_id != self.source_id:
                raise ValidationError('المقطع لا ينتمي إلى المصدر المحدد.')
            if self.evidence_text.strip() not in self.source_chunk.text:
                raise ValidationError('نص الدليل يجب أن يكون مقتطفًا من المقطع المحدد.')
            if self.page_number != self.source_chunk.page_number:
                raise ValidationError('رقم الصفحة يجب أن يطابق المقطع، أو يترك فارغًا إن لم يكن معروفًا.')

    def __str__(self):
        return self.evidence_text[:90]


class EntityRelationship(models.Model):
    from_entity = models.ForeignKey('history.Entity', verbose_name='من', on_delete=models.CASCADE, related_name='outgoing')
    to_entity = models.ForeignKey('history.Entity', verbose_name='إلى', on_delete=models.CASCADE, related_name='incoming')
    relation_type = models.CharField('العلاقة', max_length=24, choices=[
        ('PRECEDED_BY', 'سبقه'), ('FOLLOWED_BY', 'تلاه'), ('PARTICIPATED_IN', 'شارك في'), ('OCCURRED_AT', 'وقع في'),
        ('CAUSED_BY', 'نتج عن'), ('RESULTED_IN', 'أدى إلى'), ('RELATED_TO', 'مرتبط بـ'), ('MENTIONED_IN', 'ورد في'),
        ('SUPPORTED_BY', 'يدعمه'), ('TRAVELLED_TO', 'انتقل إلى'), ('CONTEMPORARY_WITH', 'عاصر'), ('NARRATED', 'روى خبر')])
    status = models.CharField('حالة المراجعة', max_length=12, choices=Status.choices, default=Status.DRAFT)
    notes = models.TextField('السياق', blank=True)
    supporting_claim = models.ForeignKey(HistoricalClaim, verbose_name='الادعاء الداعم للرابطة',
        null=True, blank=True, on_delete=models.PROTECT, related_name='supported_relationships')

    def clean(self):
        if not self.supporting_claim_id:
            return
        claim = self.supporting_claim
        if claim.event_id not in [self.from_entity_id, self.to_entity_id]:
            raise ValidationError('يجب أن يخص الدليل الحدث المرتبط بهذه الرابطة.')
        if self.from_entity.kind == 'person' and self.to_entity.kind == 'event':
            if claim.person_id != self.from_entity_id or claim.event_id != self.to_entity_id:
                raise ValidationError('دليل دور الشخصية يجب أن يطابق الشخصية والحدث واتجاه الرابطة.')
        elif self.relation_type in ['PARTICIPATED_IN', 'NARRATED']:
            raise ValidationError('يجب أن تتجه رابطة الدور من الشخصية إلى الحدث.')
        if self.relation_type in ['MENTIONED_IN', 'SUPPORTED_BY'] and self.to_entity.kind == 'source':
            if not claim.evidence.filter(source_id=self.to_entity_id).exists():
                raise ValidationError('المصدر المرتبط يجب أن يتضمن دليل الادعاء المختار.')
    class Meta:
        constraints = [models.UniqueConstraint(fields=['from_entity', 'to_entity', 'relation_type'], name='unique_relationship'), models.CheckConstraint(condition=~models.Q(from_entity=models.F('to_entity')), name='no_self_relation')]
    def __str__(self):
        return f'{self.from_entity} — {self.get_relation_type_display()} — {self.to_entity}'

from django.db import models
from django.conf import settings
import uuid

class SystemSetting(models.Model):
    key = models.CharField('المفتاح', max_length=80, unique=True)
    value = models.CharField('القيمة', max_length=500)
    description = models.CharField('الوصف', max_length=240, blank=True)
    def __str__(self):
        return self.description or self.key


class ExtractionRun(models.Model):
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    source = models.ForeignKey('sources.HistoricalSource', on_delete=models.PROTECT)
    event = models.ForeignKey('history.HistoricalEvent', on_delete=models.PROTECT)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    focus = models.CharField(max_length=800, blank=True)
    status = models.CharField(max_length=16, default='READY', choices=[('READY', 'جاهز للاستخراج'), ('RUNNING', 'جارٍ الاستخراج'), ('REVIEW', 'جاهز للمراجعة'), ('FAILED', 'تعذر الاستخراج'), ('APPLIED', 'حُفظت المسودات')])
    provider = models.CharField(max_length=30, blank=True)
    model = models.CharField(max_length=160, blank=True)
    selected_chunk_ids = models.JSONField(default=list)
    suggestions = models.JSONField(default=list)
    error_message = models.CharField(max_length=500, blank=True)
    created_claim_ids = models.JSONField(default=list)
    created_passage_ids = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']


class SourceAnalysis(models.Model):
    source = models.ForeignKey('sources.HistoricalSource', on_delete=models.PROTECT, related_name='analyses')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    configuration = models.ForeignKey('ai.ProviderConfiguration', null=True, blank=True, on_delete=models.PROTECT)
    status = models.CharField(max_length=16, default='QUEUED', choices=[('QUEUED','في قائمة التحليل'),('RUNNING','جارٍ تحليل المصدر'),('REVIEW','جاهز للمراجعة'),('PARTIAL','تحليل جزئي'),('FAILED','تعذر التحليل'),('APPLIED','حُفظت اختيارات المحرر')])
    entities = models.JSONField(default=list)
    processed_chunk_ids = models.JSONField(default=list)
    failed_chunk_ids = models.JSONField(default=list)
    error_message = models.CharField(max_length=500, blank=True)
    provider = models.CharField(max_length=30, blank=True)
    model = models.CharField(max_length=160, blank=True)
    saved_entity_ids = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

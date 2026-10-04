from django.db import models
from apps.history.models import Status

class SimulationScenario(models.Model):
    title = models.CharField('عنوان المحاكاة', max_length=240)
    event = models.ForeignKey('history.HistoricalEvent', verbose_name='الحدث', on_delete=models.CASCADE, related_name='simulations')
    decision_point = models.TextField('نقطة القرار')
    alternative = models.TextField('البديل الافتراضي')
    possible_consequences = models.TextField('النتائج المحتملة')
    influencing_factors = models.TextField('العوامل المؤثرة')
    status = models.CharField('حالة المراجعة', max_length=12, choices=Status.choices, default=Status.DRAFT)
    created_at = models.DateTimeField(auto_now_add=True)
    def __str__(self):
        return self.title

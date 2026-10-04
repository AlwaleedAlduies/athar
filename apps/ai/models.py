from django.conf import settings
from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator


class ProviderConfiguration(models.Model):
    name = models.CharField('اسم الإعداد', max_length=120)
    kind = models.CharField('المزوّد / البروتوكول', max_length=20, choices=[('local', 'Ollama'), ('gemini', 'Gemini'), ('openai', 'OpenAI'), ('compatible', 'متوافق مع OpenAI')])
    base_url = models.URLField('رابط API الأساسي', max_length=2048)
    model = models.CharField('النموذج', max_length=160)
    encrypted_key = models.TextField(blank=True, editable=False)
    timeout_seconds = models.PositiveIntegerField('مهلة الطلب بالثواني', default=180, validators=[MinValueValidator(10), MaxValueValidator(900)])
    analysis_chunk_limit = models.PositiveIntegerField('المقاطع في دورة تحليل واحدة', default=30, validators=[MinValueValidator(1), MaxValueValidator(200)])
    is_active = models.BooleanField(default=False, editable=False)
    tested_at = models.DateTimeField(null=True, editable=False)
    test_ok = models.BooleanField(default=False, editable=False)
    test_message = models.CharField(max_length=500, blank=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['is_active'], condition=models.Q(is_active=True), name='one_active_ai_provider')]

    def __str__(self):
        return self.name

    def set_key(self, value):
        from .configuration import cipher
        self.encrypted_key = cipher().encrypt(value.encode()).decode() if value else ''

    def get_key(self):
        from .configuration import cipher
        return cipher().decrypt(self.encrypted_key.encode()).decode() if self.encrypted_key else ''

class AIConversation(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    event = models.ForeignKey('history.HistoricalEvent', null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

class AIMessage(models.Model):
    conversation = models.ForeignKey(AIConversation, on_delete=models.CASCADE, related_name='messages')
    role = models.CharField(max_length=12, choices=[('user', 'مستخدم'), ('assistant', 'مرشد')])
    content = models.TextField()
    structured_answer = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

class AIQueryLog(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    question = models.TextField()
    answer = models.TextField(blank=True)
    structured_answer = models.JSONField(default=dict, blank=True)
    event = models.ForeignKey('history.HistoricalEvent', null=True, on_delete=models.SET_NULL)
    retrieved_source_ids = models.JSONField(default=list)
    retrieved_chunk_ids = models.JSONField(default=list)
    classification = models.CharField(max_length=30)
    confidence = models.CharField(max_length=60, db_index=True)
    needs_review = models.BooleanField(default=True, db_index=True)
    latency_ms = models.PositiveIntegerField(default=0)
    provider = models.CharField(max_length=40)
    model = models.CharField(max_length=100, blank=True)
    failure_reason = models.CharField(max_length=160, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ['-created_at']

"""One real provider request, through retrieval and citation validation; no retained data."""
import os
import uuid
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from apps.ai.embeddings import embedding_service
from apps.ai.services import ask
from apps.ai.models import AIQueryLog
from apps.ai.configuration import active_identity
from apps.history.models import Status
from apps.sources.models import HistoricalSource, SourceChunk


class Command(BaseCommand):
    help = 'Test the configured LLM with a temporary nonhistorical RAG fixture (one billable request).'

    def handle(self, *args, **options):
        identity = active_identity()
        provider = identity['provider']
        if provider == 'extractive':
            raise CommandError('Configure LLM_PROVIDER and credentials first.')
        engine = embedding_service()
        marker = 'atharcheck' + uuid.uuid4().hex
        with transaction.atomic():
            source = HistoricalSource.objects.create(
                title='وثيقة فحص تقني مؤقتة — ليست مصدرًا تاريخيًا', slug=marker,
                status=Status.APPROVED, is_approved=True, is_demo=False)
            content = f'{marker}: يحتوي سجل الفحص التقني على ثلاث بطاقات اختبار. هذه بيانات اصطناعية للفحص وليست معلومات تاريخية.'
            chunk = SourceChunk.objects.create(source=source, text=content,
                embedding=engine.embed(content), embedding_reference=engine.reference)
            result = ask(f'{marker}: كم بطاقة اختبار يحتوي سجل الفحص التقني؟')
            log = AIQueryLog.objects.latest('pk')
            ok = result['mode'] == ('openai' if provider == 'compatible' else provider) and any(s['chunk_id'] == chunk.pk for s in result['sources'])
            latency, failure = log.latency_ms, log.failure_reason
            transaction.set_rollback(True)
        if not ok:
            raise CommandError(f'Live RAG check failed: mode={result["mode"]}, failure={failure or "citation_missing"}. Credentials are not logged.')
        self.stdout.write(self.style.SUCCESS(f'PASS: {provider}/{identity["model"]} | retrieval + generation + citation validation | {latency} ms | temporary data rolled back'))

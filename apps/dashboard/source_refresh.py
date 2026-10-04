import uuid
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import transaction
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from apps.sources.models import HistoricalSource, SourceChunk
from apps.sources.web_import import fetch_page
from apps.sources.services import split_text
from apps.ai.embeddings import HashEmbedding
from apps.ai.configuration import safe_error
from .source_analysis import create_analysis, start_analysis
from .views import admin_required, admin_context


def save_revision(source, text, url, user, token):
    """A cleaned edition never rewrites previously reviewed citation locations."""
    with transaction.atomic():
        prior = HistoricalSource.objects.filter(slug=f'clean-{token}',replaces=source,created_by=user).first()
        if prior: return prior
        revision = HistoricalSource.objects.create(title=(source.title[:215]+' — نص منقّح'),slug=f'clean-{token}',
            replaces=source,author=source.author,source_type='digital',url=url,status='DRAFT',is_approved=False,
            created_by=user,publication_information=source.publication_information,
            description='نسخة منقّحة من نص الصفحة؛ بانتظار مراجعة المقاطع والاعتماد.')
        engine = HashEmbedding()
        SourceChunk.objects.bulk_create([SourceChunk(source=revision,ordinal=i,text=part,section=f'نص الصفحة المنقّح · مقطع {i+1}',
            embedding=engine.embed(part),embedding_reference=engine.reference) for i,part in enumerate(split_text(text))])
        revision.processed_at = timezone.now(); revision.save(update_fields=['processed_at'])
        run = create_analysis(revision,user)
        transaction.on_commit(lambda:start_analysis(run.pk))
        return revision


@admin_required
@require_POST
def refresh_source(request,pk):
    source = get_object_or_404(HistoricalSource,pk=pk)
    try:
        if not source.url or source.file:
            raise ValidationError('هذه المعاينة مخصصة لمصادر صفحات الويب.')
        if request.POST.get('action') == 'apply':
            data = signing.loads(request.POST.get('preview',''),salt='source-preview',max_age=1800)
            if data['source']!=pk or data['user']!=request.user.pk or data['original_url']!=source.url:
                raise ValidationError('تغير المصدر؛ أعد المعاينة قبل الحفظ.')
            revision = save_revision(source,data['text'],data['url'],request.user,data['token'])
            messages.success(request,'حُفظت نسخة منقّحة وبدأ تحليلها. بقيت النسخة السابقة وأدلتها محفوظة؛ راجع الجديدة قبل اعتمادها.')
            return redirect('dashboard-edit',section='sources',pk=revision.pk)
        url,text = fetch_page(source.url)
        preview = signing.dumps({'source':pk,'user':request.user.pk,'original_url':source.url,'url':url,'text':text,'token':uuid.uuid4().hex},salt='source-preview',compress=True)
        return render(request,'dashboard/source_preview.html',admin_context(section='sources',source=source,text=text,preview=preview,
            old_chars=sum(len(c.text) for c in source.chunks.all()),new_chars=len(text)))
    except signing.BadSignature:
        messages.error(request,'انتهت صلاحية المعاينة أو تغيرت؛ أعد قراءة الصفحة.')
    except Exception as exc:
        messages.error(request,safe_error(exc))
    return redirect('dashboard-edit',section='sources',pk=pk)

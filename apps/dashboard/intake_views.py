import uuid
from datetime import timedelta
from django import forms
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from apps.ai.embeddings import HashEmbedding
from apps.ai.configuration import active_identity, active_configuration, safe_error
from apps.history.models import Entity, HistoricalEra, Status
from apps.sources.models import HistoricalSource, SourceChunk
from apps.sources.services import process_source, split_text
from apps.sources.validators import validate_document
from apps.sources.web_import import fetch_page
from .models import SourceAnalysis
from apps.knowledge.models import HistoricalClaim
from .source_analysis import create_analysis, start_analysis, save_discoveries, matching_entities
from .views import admin_required, admin_context


class IntakeForm(forms.Form):
    token=forms.UUIDField(widget=forms.HiddenInput,initial=uuid.uuid4)
    title=forms.CharField(label='عنوان المصدر',max_length=240)
    author=forms.CharField(label='المؤلف أو الجهة',max_length=240,required=False)
    input_kind=forms.ChoiceField(label='نوع المصدر',choices=[('file','ملف PDF / DOCX / TXT'),('url','رابط صفحة عامة')],widget=forms.RadioSelect,initial='file')
    document=forms.FileField(label='الملف',required=False,validators=[validate_document],widget=forms.ClearableFileInput(attrs={'accept':'.pdf,.docx,.txt'}))
    url=forms.URLField(label='رابط الصفحة',max_length=2048,required=False,widget=forms.URLInput(attrs={'dir':'ltr'}))

    def clean(self):
        data=super().clean(); required='document' if data.get('input_kind')=='file' else 'url'
        if not data.get(required): self.add_error(required,'أكمل هذا الحقل.')
        return data


class EntityDecisionForm(forms.Form):
    action=forms.ChoiceField(label='ماذا نفعل بهذا الاسم؟',choices=[('skip','تجاهل الآن'),('link','اربط بسجل موجود'),('create','أضف سجلًا جديدًا كمسودة')])
    entity=forms.ModelChoiceField(label='السجل الموجود',queryset=Entity.objects.none(),required=False)
    title=forms.CharField(label='عنوان السجل الجديد',max_length=240,required=False)
    description=forms.CharField(label='وصف المسودة الجديدة',max_length=3000,required=False,widget=forms.Textarea(attrs={'rows':3}))
    era=forms.ModelChoiceField(label='حقبة الحدث الجديد',queryset=HistoricalEra.objects.filter(deleted_at__isnull=True,is_demo=False),required=False)

    def __init__(self,*args,kind,**kwargs):
        super().__init__(*args,**kwargs)
        self.kind=kind
        self.fields['entity'].queryset=Entity.objects.filter(kind=kind,deleted_at__isnull=True,is_demo=False)
        if kind!='event': self.fields.pop('era')

    def clean(self):
        data=super().clean()
        if data.get('action')=='link' and not data.get('entity'): self.add_error('entity','اختر السجل الذي تحققت من مطابقته.')
        if data.get('action')=='create':
            if not data.get('title'): self.add_error('title','اكتب اسم السجل الجديد.')
            if self.kind=='event' and not data.get('era'): self.add_error('era','حدد حقبة الحدث.')
        return data


@admin_required
def intake(request):
    form=IntakeForm(request.POST or None,request.FILES or None)
    if request.method=='POST' and form.is_valid():
        data=form.cleaned_data; slug=f'intake-{data["token"].hex}'
        prior=HistoricalSource.objects.filter(slug=slug,created_by=request.user).first()
        if prior and prior.analyses.exists(): return redirect('source-analysis',pk=prior.analyses.first().pk)
        source=None; upload=None
        try:
            final_url,text=fetch_page(data['url']) if data['input_kind']=='url' else ('','')
            with transaction.atomic():
                source=HistoricalSource.objects.create(title=data['title'],slug=slug,author=data['author'],url=final_url,
                    source_type='digital' if text else 'other',file=data['document'] if data['input_kind']=='file' else '',
                    status=Status.DRAFT,is_approved=False,created_by=request.user)
                if text:
                    engine=HashEmbedding()
                    SourceChunk.objects.bulk_create([SourceChunk(source=source,ordinal=i,text=part,section=f'نص الصفحة · مقطع {i+1}',
                        embedding=engine.embed(part),embedding_reference=engine.reference) for i,part in enumerate(split_text(text))])
                    source.processed_at=timezone.now(); source.save(update_fields=['processed_at'])
                else:
                    upload=source.file.name; process_source(source)
                run=create_analysis(source,request.user)
                transaction.on_commit(lambda:start_analysis(run.pk))
            return redirect('source-analysis',pk=run.pk)
        except Exception as exc:
            if upload: source.file.storage.delete(upload)
            form.add_error(None,safe_error(exc))
    return render(request,'dashboard/intake.html',admin_context(section='intake',form=form,active=active_identity(),
        runs=SourceAnalysis.objects.select_related('source')[:20]))


def analysis_context(run):
    total=run.source.chunks.count(); processed=len(run.processed_chunk_ids)
    timeout=run.configuration.timeout_seconds if run.configuration_id else 300
    stale=run.updated_at < timezone.now()-timedelta(seconds=timeout+90)
    return {'total':total,'processed':processed,'progress':round(processed/max(total,1)*100),
        'remaining':max(0,total-processed),'can_retry':run.status in ['QUEUED','FAILED','PARTIAL'] or (run.status=='RUNNING' and stale)}


@admin_required
def analysis_detail(request,pk):
    run=get_object_or_404(SourceAnalysis.objects.select_related('source','configuration'),pk=pk)
    chunks={c.pk:c for c in run.source.chunks.all()}
    rows=[]; selected={}; valid=True
    for index,row in enumerate(run.entities):
        matches=matching_entities(row)
        initial={'action':'skip','title':row['name'],'description':row['summary']}
        if len([m for m in matches if m['exact']])==1:
            initial.update(action='link',entity=next(m['entity'].pk for m in matches if m['exact']))
        form=EntityDecisionForm(request.POST if request.method=='POST' else None,prefix=str(index),kind=row['kind'],initial=initial)
        if request.method=='POST':
            if form.is_valid():
                d=form.cleaned_data
                if d['action']!='skip': selected[index]={'action':d['action'],'entity_id':d['entity'].pk if d.get('entity') else None,
                    'title':d['title'],'description':d['description'],'era_id':d['era'].pk if d.get('era') else None}
            else: valid=False
        rows.append({'item':row,'kind_label':dict(Entity.Kind.choices).get(row['kind']),'form':form,'matches':matches,
            'refs':[{**ref,'chunk':chunks.get(ref['chunk_id'])} for ref in row['evidence']]})
    if request.method=='POST' and valid:
        try:
            save_discoveries(run,selected,request.user)
            messages.success(request,'حُفظت روابط الذكر ومسودات السجلات الجديدة. راجع المصدر وروابطه قبل إظهارها للعامة.')
            return redirect('source-analysis',pk=pk)
        except ValidationError as exc: messages.error(request,' '.join(exc.messages))
    return render(request,'dashboard/analysis.html',admin_context(section='intake',run=run,rows=rows,**analysis_context(run),
        saved=Entity.objects.filter(pk__in=run.saved_entity_ids),mentions=run.source.mentions.filter(analysis=run).select_related('entity'),
        draft_claims=HistoricalClaim.objects.filter(review_notes__startswith=f'تحليل مصدر {run.pk}؛')))


@admin_required
def analysis_status(request,pk):
    run=get_object_or_404(SourceAnalysis.objects.select_related('source','configuration'),pk=pk)
    return JsonResponse({'status':run.status,'label':run.get_status_display(),'entities':len(run.entities),**analysis_context(run)})


@admin_required
@require_POST
def retry_analysis(request,pk):
    with transaction.atomic():
        run=get_object_or_404(SourceAnalysis.objects.select_for_update(of=('self',)).select_related('source','configuration'),pk=pk)
        if not analysis_context(run)['can_retry']:
            messages.error(request,'الطلب قيد التنفيذ أو اكتملت مراجعته.')
        else:
            run.configuration=active_configuration(); run.status='QUEUED'; run.error_message=''; run.save()
            transaction.on_commit(lambda:start_analysis(run.pk))
    return redirect('source-analysis',pk=pk)


@admin_required
@require_POST
def analyze_existing(request,pk):
    source=get_object_or_404(HistoricalSource,pk=pk)
    try:
        with transaction.atomic():
            if not source.chunks.exists(): process_source(source)
            run=create_analysis(source,request.user)
            transaction.on_commit(lambda:start_analysis(run.pk))
        return redirect('source-analysis',pk=run.pk)
    except Exception as exc:
        messages.error(request,safe_error(exc))
        return redirect('dashboard-edit',section='sources',pk=pk)

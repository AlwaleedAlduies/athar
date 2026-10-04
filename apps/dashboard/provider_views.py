import json
from django import forms
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from apps.ai.models import ProviderConfiguration
from apps.ai.configuration import validate_endpoint, active_identity, safe_error
from apps.ai.providers import get_provider
from .views import admin_required, admin_context


class ProviderForm(forms.ModelForm):
    api_key = forms.CharField(label='مفتاح API (اختياري محليًا)', required=False, max_length=2000, widget=forms.PasswordInput(render_value=False), help_text='اتركه فارغًا للإبقاء على المفتاح. عند تغيير المزوّد أو الرابط لا ينتقل المفتاح السابق. للمزوّد الرسمي يُستخدم مفتاح البيئة إن لم تحفظ مفتاحًا هنا.')
    clear_key = forms.BooleanField(label='امسح المفتاح المحفوظ لهذا الإعداد', required=False)
    class Meta:
        model = ProviderConfiguration
        fields = ['name','kind','base_url','model','timeout_seconds','analysis_chunk_limit']
        widgets = {'base_url':forms.URLInput(attrs={'dir':'ltr'}), 'model':forms.TextInput(attrs={'dir':'ltr'})}

    def clean(self):
        data = super().clean()
        if data.get('kind') and data.get('base_url'):
            data['base_url'] = validate_endpoint(data['base_url'], data['kind'])
        return data


def check_connection(config):
    try:
        value = get_provider(config).generate('Return a JSON object with exactly one property: "ok": true. No other text.',
            {'task':'connection test'}, max_tokens=60, schema={'type':'object','properties':{'ok':{'type':'boolean'}},'required':['ok']})
        if json.loads(value).get('ok') is not True:
            raise ValidationError('وصل رد من النموذج لكنه لم يطابق فحص JSON.')
        config.test_ok, config.test_message = True, 'نجح اتصال API والتوليد المنظم من النموذج.'
    except Exception as exc:
        config.test_ok, config.test_message = False, safe_error(exc)
    config.tested_at = timezone.now()
    config.save(update_fields=['tested_at','test_ok','test_message'])
    return config.test_ok


@admin_required
def providers(request, pk=None):
    instance = get_object_or_404(ProviderConfiguration, pk=pk) if pk else None
    old_endpoint = (instance.kind, instance.base_url.rstrip('/')) if instance else None
    initial = {} if instance else {'kind':'local','base_url':'http://127.0.0.1:11434','model':'phi4:latest','timeout_seconds':600}
    form = ProviderForm(request.POST or None, instance=instance, initial=initial)
    if request.method == 'POST' and form.is_valid():
        config = form.save(commit=False)
        if old_endpoint and old_endpoint != (config.kind, config.base_url.rstrip('/')):
            config.set_key('')
        if form.cleaned_data['clear_key']:
            config.set_key('')
        if form.cleaned_data['api_key']:
            config.set_key(form.cleaned_data['api_key'])
        if form.has_changed():
            if config.is_active:
                config.pk = None
                config._state.adding = True
            config.test_ok = False; config.tested_at = None; config.test_message = ''
            # An edited endpoint must pass testing before it can receive application traffic.
            config.is_active = False
        config.save()
        if request.POST.get('action') == 'test':
            check_connection(config)
            messages.add_message(request, messages.SUCCESS if config.test_ok else messages.ERROR, config.test_message)
        else:
            messages.success(request,'حُفظ الإعداد. اختبره ثم فعّله للاستخدام في خدمات المنصة.')
        return redirect('ai-provider-edit', pk=config.pk)
    return render(request,'dashboard/providers.html', admin_context(section='providers',form=form,config=instance,
        configs=ProviderConfiguration.objects.order_by('-is_active','pk'),active=active_identity()))


@admin_required
@require_POST
def activate(request, pk):
    with transaction.atomic():
        config = get_object_or_404(ProviderConfiguration.objects.select_for_update(), pk=pk)
        if not config.test_ok:
            messages.error(request,'اختبر هذا الإعداد بنجاح قبل تفعيله.')
        else:
            ProviderConfiguration.objects.filter(is_active=True).update(is_active=False)
            config.is_active = True; config.save(update_fields=['is_active'])
            messages.success(request,'فُعّل المزوّد للأسئلة والمحاكاة واستخراج المعرفة. تستخدم المهام الجديدة هذا الإعداد.')
    return redirect('ai-provider-edit', pk=pk)

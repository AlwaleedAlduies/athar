from django.conf import settings

def site_context(request):
    from apps.dashboard.models import SystemSetting
    return {'demo_mode': settings.DEMO_MODE, 'site_settings': dict(SystemSetting.objects.values_list('key', 'value'))}

import json
from django.contrib.auth import login, logout
from django.contrib.auth.forms import AuthenticationForm
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods
from .forms import RegistrationForm, ProfileForm
from .models import UserProfile
from .views import auth_limited

@csrf_protect
@require_http_methods(['GET', 'POST'])
def auth_api(request, operation='session'):
    if request.method == 'GET':
        return JsonResponse({'authenticated': request.user.is_authenticated,
                             'user': {'username': request.user.username, 'role': 'ADMIN' if request.user.is_admin else 'USER'} if request.user.is_authenticated else None,
                             'csrf_token': get_token(request)})
    if auth_limited(request):
        return JsonResponse({'error': 'محاولات كثيرة. يرجى المحاولة لاحقًا.'}, status=429)
    try:
        data = json.loads(request.body) if request.content_type == 'application/json' else request.POST
        if not isinstance(data, dict):
            raise ValueError()
    except (ValueError, UnicodeError):
        return JsonResponse({'error': 'بيانات غير صالحة.'}, status=400)
    if operation == 'logout':
        logout(request)
        return JsonResponse({'ok': True})
    if operation == 'profile':
        if not request.user.is_authenticated:
            return JsonResponse({'error': 'سجّل الدخول أولًا.'}, status=403)
        form = ProfileForm(data, instance=request.user)
    elif operation == 'register':
        form = RegistrationForm(data)
    elif operation == 'login':
        form = AuthenticationForm(request, data=data)
    else:
        return JsonResponse({'error': 'إجراء غير معروف.'}, status=404)
    if not form.is_valid():
        return JsonResponse({'error': form.errors.get_json_data()}, status=400)
    if operation == 'login':
        user = form.get_user()
    else:
        user = form.save()
    if operation == 'register':
        UserProfile.objects.get_or_create(user=user)
    if operation != 'profile':
        login(request, user)
    return JsonResponse({'ok': True, 'username': user.username})

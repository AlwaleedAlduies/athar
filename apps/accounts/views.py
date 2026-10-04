from django.contrib.auth import login
from django.contrib.auth.views import LoginView
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.cache import cache
from django.shortcuts import render, redirect
from .forms import RegistrationForm, ProfileForm, ArabicAuthenticationForm
from .models import UserProfile

def auth_limited(request):
    key = 'auth:' + request.META.get('REMOTE_ADDR', '')
    count = cache.get(key, 0)
    cache.set(key, count + 1, 3600)
    return count >= 30

class AtharLoginView(LoginView):
    authentication_form = ArabicAuthenticationForm
    template_name = 'accounts/auth.html'
    redirect_authenticated_user = True
    def post(self, request, *args, **kwargs):
        if auth_limited(request):
            return render(request, 'error.html', {'message': 'محاولات كثيرة. يرجى المحاولة لاحقًا.'}, status=429)
        return super().post(request, *args, **kwargs)

def register(request):
    if request.method == 'POST' and auth_limited(request):
        return render(request, 'error.html', {'message': 'محاولات كثيرة. يرجى المحاولة لاحقًا.'}, status=429)
    form = RegistrationForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        UserProfile.objects.create(user=user)
        login(request, user)
        return redirect('discover')
    return render(request, 'accounts/auth.html', {'form': form, 'register': True})

@login_required
def profile(request):
    form = ProfileForm(request.POST or None, instance=request.user)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'حُفظت بياناتك.')
        return redirect('profile')
    return render(request, 'accounts/profile.html', {'form': form})

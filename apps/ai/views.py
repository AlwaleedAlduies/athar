from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, render
from apps.accounts.permissions import is_admin
from .models import AIQueryLog


@login_required
def answer_history(request):
    rows = AIQueryLog.objects.filter(user=request.user).select_related('event')
    return render(request,'ai/history.html',{'page':Paginator(rows,20).get_page(request.GET.get('page'))})


@login_required
def answer_detail(request,pk):
    rows = AIQueryLog.objects.select_related('event','user')
    if not is_admin(request.user): rows = rows.filter(user=request.user)
    log = get_object_or_404(rows,pk=pk)
    return render(request,'ai/answer.html',{'log':log,'admin_view':is_admin(request.user)})

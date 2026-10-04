from django.contrib import admin
from django.contrib.auth.views import LogoutView
from django.urls import path, include
from django.views.decorators.csrf import csrf_protect
from rest_framework.routers import DefaultRouter
from apps.accounts.views import AtharLoginView, register, profile
from apps.accounts.api import auth_api
from apps.history import views, api
from apps.dashboard import views as dashboard
from apps.dashboard import import_views
from apps.dashboard import provider_views
from apps.dashboard import intake_views
from apps.ai import views as ai_views
from apps.dashboard.source_refresh import refresh_source
from apps.dashboard.forms import REGISTRY
from config.health import health

router = DefaultRouter()
router.register('events', api.EventViewSet, basename='event')
router.register('sources', api.SourceViewSet, basename='source')
router.register('claims', api.ClaimViewSet, basename='claim')
router.register('passages', api.PassageViewSet, basename='passage')
router.register('simulations', api.SimulationViewSet, basename='simulation')
router.register('bookmarks', api.BookmarkViewSet, basename='bookmark')
for section in ['persons', 'places', 'eras', 'evidence', 'relationships']:
    model = REGISTRY[section][0]
    router.register(section, type(model.__name__ + 'ViewSet', (api.ContentViewSet,), {'model': model}), basename=section)

urlpatterns = [
    path('healthz/', health, name='health'),
    path('', views.landing, name='landing'), path('discover/', views.discover, name='discover'),
    path('journey/', views.journey, name='journey'),
    path('timeline/', views.timeline, name='timeline'), path('explore/<int:pk>/', views.detail, name='detail'),
    path('search/', views.search, name='search'), path('library/', views.library, name='library'),
    path('library/answers/', ai_views.answer_history, name='answer-history'),
    path('library/answers/<int:pk>/', ai_views.answer_detail, name='answer-detail'),
    path('dashboard/sources/<int:pk>/approve/', dashboard.approve_source, name='source-approve'),
    path('dashboard/sources/<int:pk>/refresh/', refresh_source, name='source-refresh'),
    path('sources/<int:pk>/download/', views.source_download, name='source-download'),
    path('login/', AtharLoginView.as_view(), name='login'), path('register/', register, name='register'),
    path('logout/', LogoutView.as_view(), name='logout'), path('profile/', profile, name='profile'),
    path('dashboard/', dashboard.dashboard, name='dashboard'),
    path('dashboard/editor-options/', dashboard.editor_options, name='editor-options'),
    path('dashboard/intake/', intake_views.intake, name='source-intake'),
    path('dashboard/intake/<int:pk>/', intake_views.analysis_detail, name='source-analysis'),
    path('dashboard/intake/<int:pk>/status/', intake_views.analysis_status, name='source-analysis-status'),
    path('dashboard/intake/<int:pk>/retry/', intake_views.retry_analysis, name='source-analysis-retry'),
    path('dashboard/sources/<int:pk>/analyze/', intake_views.analyze_existing, name='source-analyze'),
    path('dashboard/ai-providers/', provider_views.providers, name='ai-providers'),
    path('dashboard/ai-providers/<int:pk>/', provider_views.providers, name='ai-provider-edit'),
    path('dashboard/ai-providers/<int:pk>/activate/', provider_views.activate, name='ai-provider-activate'),
    path('dashboard/studio/', import_views.studio, name='extraction-studio'),
    path('dashboard/studio/<int:pk>/', import_views.run_detail, name='extraction-run'),
    path('dashboard/studio/<int:pk>/extract/', import_views.extract, name='extraction-generate'),
    path('dashboard/<str:section>/', dashboard.collection, name='dashboard-list'),
    path('dashboard/<str:section>/new/', dashboard.edit, name='dashboard-new'),
    path('dashboard/<str:section>/<int:pk>/', dashboard.edit, name='dashboard-edit'),
    path('dashboard/<str:section>/<int:pk>/remove/', dashboard.remove, name='dashboard-remove'),
    path('dashboard/<str:section>/<int:pk>/delete/', dashboard.removal_preview, name='dashboard-removal-preview'),
    path('dashboard/<str:section>/<int:pk>/restore/', dashboard.restore, name='dashboard-restore'),
    path('dashboard/sources/<int:pk>/process/', dashboard.process, name='dashboard-source-process'),
    path('dashboard/events/<int:pk>/suggest/', dashboard.suggest, name='event-suggest'),
    path('api/v1/auth/', auth_api), path('api/v1/auth/<str:operation>/', auth_api),
    path('api/v1/search/', api.search_api), path('api/v1/ai/ask/', csrf_protect(api.ask_api)),
    path('api/v1/', include(router.urls)), path('dev-admin/', admin.site.urls),
]

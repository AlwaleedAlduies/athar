import copy
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import serializers, viewsets, status
from rest_framework.decorators import action, api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle
from apps.accounts.permissions import is_admin, AdminOnly
from apps.accounts.models import Bookmark
from apps.dashboard.forms import REGISTRY, validate_editorial
from apps.sources.models import HistoricalSource
from apps.sources.services import process_source
from apps.knowledge.models import HistoricalClaim, Evidence, EntityRelationship
from apps.knowledge.selectors import graph_for, public_claims, approved_evidence, public_relationships, trace_claim
from apps.ai.services import ask
from apps.simulations.models import SimulationScenario
from apps.simulations.services import run_simulation
from .models import Entity, HistoricalEvent, StoryPassage, Status
from .story import public_passages, passage_trace, validate_citations
from .search import search_entities

class EditorialSerializer(serializers.ModelSerializer):
    def validate(self, attrs):
        instance = copy.copy(self.instance) if self.instance else self.Meta.model()
        many = {field.name for field in instance._meta.many_to_many}
        for key, value in attrs.items():
            if key not in many:
                setattr(instance, key, value)
        try:
            if isinstance(instance, StoryPassage):
                validate_citations(instance, attrs.get('citations', instance.citations.all() if instance.pk else []))
            instance.full_clean(exclude=[*many, 'entity_ptr', 'kind'])
            validate_editorial(instance, attrs.get('citations') if isinstance(instance, StoryPassage) else None)
            if isinstance(instance, HistoricalSource) and self.instance and 'file' in attrs and attrs['file'] != self.instance.file and self.instance.chunks.exists():
                raise DjangoValidationError('أنشئ مصدرًا جديدًا لتغيير ملف ذي مقاطع محفوظة.')
        except DjangoValidationError as error:
            raise serializers.ValidationError(error.message_dict if hasattr(error, 'message_dict') else error.messages)
        return attrs

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get('request')
        if not request or not is_admin(request.user):
            for key in ['created_by', 'reviewed_by', 'approved_by', 'review_notes', 'file', 'deleted_at']:
                data.pop(key, None)
            if isinstance(instance, HistoricalEvent):
                visible_ids = set(Entity.objects.visible().values_list('pk', flat=True))
                for key in ['persons', 'places', 'sources', 'related_events']:
                    data[key] = [pk for pk in data.get(key, []) if pk in visible_ids]
                for key in ['era', 'location']:
                    if data.get(key) not in visible_ids:
                        data[key] = None
        if isinstance(instance, Entity):
            data['url'] = instance.get_absolute_url()
        return data

def serializer_for(model):
    meta = type('Meta', (), {'model': model, 'fields': '__all__', 'read_only_fields': ['created_by', 'reviewed_by', 'approved_by', 'created_at', 'updated_at', 'processed_at', 'deleted_at', 'kind']})
    return type(model.__name__ + 'Serializer', (EditorialSerializer,), {'Meta': meta})

class ContentViewSet(viewsets.ModelViewSet):
    model = None
    def get_serializer_class(self):
        return serializer_for(self.model)
    def get_queryset(self):
        queryset = self.model.objects.all()
        if is_admin(self.request.user):
            return queryset.order_by('-pk')
        if issubclass(self.model, Entity):
            return queryset.visible()
        if self.model == HistoricalClaim:
            return public_claims()
        if self.model == StoryPassage:
            return public_passages()
        if self.model == Evidence:
            return approved_evidence()
        if self.model == EntityRelationship:
            return public_relationships()
        if self.model == SimulationScenario:
            return queryset.filter(status__in=[Status.APPROVED, Status.PUBLISHED], event__in=Entity.objects.visible())
        return queryset.none()
    def perform_create(self, serializer):
        extra = {'created_by': self.request.user} if hasattr(self.model, 'created_by') else {}
        with transaction.atomic():
            instance = serializer.save(**extra)
            self.stamp_review(instance)
    def perform_update(self, serializer):
        with transaction.atomic():
            self.stamp_review(serializer.save())
    def stamp_review(self, instance):
        if getattr(instance, 'status', None) in [Status.APPROVED, Status.PUBLISHED]:
            for field in ['reviewed_by', 'approved_by']:
                if hasattr(instance, field):
                    setattr(instance, field, self.request.user)
            instance.save()
            if isinstance(instance, StoryPassage):
                from .story import sync_story_references
                sync_story_references(instance)
    def perform_destroy(self, instance):
        if hasattr(instance, 'status'):
            instance.status = Status.ARCHIVED
            if hasattr(instance, 'is_approved'):
                instance.is_approved = False
            instance.save()
        else:
            instance.delete()

class EventViewSet(ContentViewSet):
    model = HistoricalEvent
    def get_queryset(self):
        queryset = super().get_queryset().select_related('era', 'location').prefetch_related('persons', 'places', 'sources', 'related_events')
        params = self.request.query_params
        if params.get('era', '').isdigit():
            queryset = queryset.filter(era_id=params['era'])
        if params.get('type'):
            queryset = queryset.filter(event_type=params['type'])
        return queryset
    @action(detail=True, methods=['get'])
    def graph(self, request, pk=None):
        return Response(graph_for(self.get_object()))
    @action(detail=True, methods=['get'])
    def claims(self, request, pk=None):
        return Response({'results': [trace_claim(c) for c in public_claims().filter(event=self.get_object())]})

class SourceViewSet(ContentViewSet):
    model = HistoricalSource
    @action(detail=True, methods=['post'], permission_classes=[AdminOnly])
    def process(self, request, pk=None):
        try:
            count = process_source(self.get_object())
        except DjangoValidationError as error:
            raise serializers.ValidationError(error.messages)
        except Exception:
            raise serializers.ValidationError('تعذرت معالجة الملف أو خدمة التضمين.')
        return Response({'chunks_created': count})
    @action(detail=True, methods=['get'], permission_classes=[AdminOnly])
    def chunks(self, request, pk=None):
        chunks = self.get_object().chunks.all().values('id', 'page_number', 'section', 'text', 'embedding_reference')
        page = self.paginate_queryset(chunks)
        return self.get_paginated_response(page)

class ClaimViewSet(ContentViewSet):
    model = HistoricalClaim
    @action(detail=True, methods=['get'])
    def evidence(self, request, pk=None):
        return Response(trace_claim(self.get_object()))


class PassageViewSet(ContentViewSet):
    model = StoryPassage

    @action(detail=True, methods=['get'])
    def citations(self, request, pk=None):
        return Response(passage_trace(get_object_or_404(public_passages(), pk=pk)))

class AIThrottle(SimpleRateThrottle):
    scope = 'ai'
    def get_cache_key(self, request, view):
        return self.cache_format % {'scope': self.scope, 'ident': request.user.pk if request.user.is_authenticated else self.get_ident(request)}

class AskSerializer(serializers.Serializer):
    question = serializers.CharField(max_length=1200, min_length=3)
    event_id = serializers.IntegerField(required=False, allow_null=True)

@api_view(['POST'])
@permission_classes([AllowAny])
@throttle_classes([AIThrottle])
def ask_api(request):
    form = AskSerializer(data=request.data)
    form.is_valid(raise_exception=True)
    event_id = form.validated_data.get('event_id')
    event = get_object_or_404(HistoricalEvent.objects.visible(), pk=event_id) if event_id else None
    return Response(ask(form.validated_data['question'], request.user, event))

@api_view(['GET'])
@permission_classes([AllowAny])
def search_api(request):
    query = request.GET.get('q', '')[:200]
    results = search_entities(query)
    from rest_framework.pagination import PageNumberPagination
    paginator = PageNumberPagination()
    rows = paginator.paginate_queryset(results, request)
    return paginator.get_paginated_response([{'id': e.pk, 'title': e.title, 'kind': e.kind, 'url': e.get_absolute_url(), 'description': e.description} for e in rows])

class SimulationViewSet(ContentViewSet):
    model = SimulationScenario
    @action(detail=True, methods=['post'], permission_classes=[AllowAny], throttle_classes=[AIThrottle])
    def run(self, request, pk=None):
        scenario = self.get_object()
        if request.data.get('acknowledged') is not True:
            raise serializers.ValidationError('يجب تأكيد دخول المحاكاة التعليمية أولًا.')
        choice = request.data.get('choice', '')
        if not isinstance(choice, str) or len(choice) > 600:
            raise serializers.ValidationError('اكتب بديلًا لا يتجاوز ٦٠٠ حرف.')
        return Response(run_simulation(scenario, choice))

class BookmarkSerializer(serializers.ModelSerializer):
    entity = serializers.PrimaryKeyRelatedField(queryset=Entity.objects.visible())
    title = serializers.CharField(source='entity.title', read_only=True)
    url = serializers.CharField(source='entity.get_absolute_url', read_only=True)
    class Meta:
        model = Bookmark
        fields = ['id', 'entity', 'title', 'url', 'created_at']
        read_only_fields = ['created_at']

class BookmarkViewSet(viewsets.ModelViewSet):
    serializer_class = BookmarkSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ['get', 'post', 'delete', 'head', 'options']
    def get_queryset(self):
        return Bookmark.objects.filter(user=self.request.user, entity__in=Entity.objects.visible()).select_related('entity')
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        item, created = Bookmark.objects.get_or_create(user=request.user, entity=serializer.validated_data['entity'])
        return Response(self.get_serializer(item).data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)
    @action(detail=False, methods=['post'])
    def toggle(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            item, created = Bookmark.objects.get_or_create(user=request.user, entity=serializer.validated_data['entity'])
            if not created:
                item.delete()
        return Response({'saved': created})

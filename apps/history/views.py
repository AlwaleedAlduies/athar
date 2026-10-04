from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, render
from apps.accounts.models import Bookmark, ExplorationHistory, SearchHistory
from apps.accounts.permissions import is_admin
from apps.knowledge.selectors import public_claims, public_relationships, graph_for, trace_claim
from django.db.models import Q
from apps.sources.models import HistoricalSource
from .models import Entity, HistoricalEvent, HistoricalEra, HistoricalPerson, HistoricalPlace, Status
from .search import search_entities
from .story import public_passages
from apps.knowledge.selectors import public_mentions

def landing(request):
    events = list(HistoricalEvent.objects.visible().select_related('location', 'era')[:3])
    return render(request, 'history/landing.html', {'events': events, 'has_demo_events': any(e.is_demo for e in events)})

def journey(request):
    """A public, chronological reading path; unpublished relations stay private."""
    events = HistoricalEvent.objects.visible().select_related('era', 'location').order_by('year_order', 'pk')
    focused = request.GET.get('path') == 'medina'
    if focused:
        events = events.filter(slug__in=['badr', 'uhud', 'khandaq'])
    visible_ids = set(Entity.objects.visible().values_list('pk', flat=True))
    stations = []
    for event in events:
        story = list(public_passages().filter(event=event).values('id', 'chapter', 'text'))
        has_story = event.story_passages.filter(status__in=[Status.APPROVED, Status.PUBLISHED]).exists()
        stations.append({
            'id': event.pk, 'title': event.title, 'url': event.get_absolute_url(),
            'year': event.year_order, 'date': event.hijri_label or 'تاريخ غير محدد',
            'gregorian': event.gregorian_label, 'precision': event.get_date_precision_display(),
            'type': event.get_event_type_display(), 'tone': event.event_type, 'demo': event.is_demo,
            'era': event.era.title if event.era_id in visible_ids else '',
            'place': event.location.title if event.location_id in visible_ids else '',
            'description': event.description, 'narrative': event.narrative if not has_story else '',
            'context': event.context if not has_story else '', 'consequences': event.consequences if not has_story else '',
            'story': story,
            'people': list(event.persons.visible().values('id', 'title')[:4]),
            'sources': list(event.sources.visible().filter(is_approved=True, is_demo=False).values('id', 'title')[:6]),
        })
    return render(request, 'history/journey.html', {'stations': stations, 'focused': focused})

def discover(request):
    recent = ExplorationHistory.objects.filter(user=request.user, entity__in=Entity.objects.visible()).select_related('entity')[:4] if request.user.is_authenticated else []
    saved = Bookmark.objects.filter(user=request.user, entity__in=Entity.objects.visible()).select_related('entity')[:4] if request.user.is_authenticated else []
    return render(request, 'history/discover.html', {'events': HistoricalEvent.objects.visible().select_related('era', 'location'), 'eras': HistoricalEra.objects.visible(), 'recent': recent, 'saved': saved,
        'focus_available': public_claims().filter(review_notes__startswith='medina-focus-v1:').exists()})

def timeline(request):
    events = HistoricalEvent.objects.visible().select_related('era', 'location')
    if request.GET.get('era', '').isdigit():
        events = events.filter(era_id=request.GET['era'])
    if request.GET.get('type'):
        events = events.filter(event_type=request.GET['type'])
    query = request.GET.get('q', '')[:200]
    if query:
        ids = [e.pk for e in search_entities(query, events)]
        events = events.filter(pk__in=ids)
    page = Paginator(events, 18).get_page(request.GET.get('page'))
    return render(request, 'history/timeline.html', {'page': page, 'has_demo_events': any(e.is_demo for e in page),
                  'eras': HistoricalEra.objects.visible(), 'types': HistoricalEvent.EventType.choices, 'query': query})

def detail(request, pk):
    entity = get_object_or_404(Entity.objects.visible(), pk=pk)
    if request.user.is_authenticated:
        ExplorationHistory.objects.update_or_create(user=request.user, entity=entity)
    graph = graph_for(entity)
    context = {'entity': entity, 'graph': graph,
               'bookmarked': request.user.is_authenticated and Bookmark.objects.filter(user=request.user, entity=entity).exists()}
    supported_links = public_relationships().filter(Q(from_entity=entity) | Q(to_entity=entity), supporting_claim__isnull=False)
    context['supported_links'] = supported_links
    context['source_mentions'] = public_mentions().filter(Q(entity_id=entity.pk) | Q(source_id=entity.pk))
    if entity.kind == 'event':
        event = get_object_or_404(HistoricalEvent.objects.select_related('era', 'location'), pk=pk)
        visible_ids = set(Entity.objects.visible().values_list('pk', flat=True))
        event.visible_era = event.era if event.era_id in visible_ids else None
        event.visible_location = event.location if event.location_id in visible_ids else None
        claims = list(public_claims().filter(event=event))
        passages = list(public_passages().filter(event=event))
        story_count = event.story_passages.filter(status__in=[Status.APPROVED, Status.PUBLISHED]).count()
        words = sum(len(p.text.split()) for p in passages)
        people = list(event.persons.visible())
        role_links = list(supported_links.filter(from_entity__kind='person', to_entity=event))
        for person in people:
            person.role_links = [link for link in role_links if link.from_entity_id == person.pk]
        places = list(event.places.visible())
        place_links = list(supported_links.filter(from_entity=event, to_entity__kind='place'))
        for place in places:
            place.evidence_links = [link for link in place_links if link.to_entity_id == place.pk]
        route = list(HistoricalEvent.objects.visible().order_by('year_order', 'pk'))
        current = next(i for i, stop in enumerate(route) if stop.pk == event.pk)
        context.update(previous_event=route[current - 1] if current else None,
                       next_event=route[current + 1] if current + 1 < len(route) else None)
        for claim in claims:
            trace = trace_claim(claim)
            claim.has_direct_support = trace['confidence'] == 'موثق'
            claim.public_classification = trace['classification']
        context.update(event=event, people=people, places=places,
                       sources=event.sources.visible().filter(is_approved=True, is_demo=False), claims=claims,
                       reference_sources=event.sources.visible().filter(is_approved=True, is_demo=False, source_type='digital'),
                       related=event.related_events.visible(), scenarios=event.simulations.filter(status__in=[Status.APPROVED, Status.PUBLISHED]),
                       event_links=supported_links.filter(from_entity__kind='event', to_entity__kind='event'),
                       focused=any(c.review_notes.startswith('medina-focus-v1:') for c in claims))
        context.update(story_passages=passages, has_story=bool(story_count), story_missing=story_count - len(passages),
                       reading_minutes=max(1, round(words / 160)), story_words=words)
        return render(request, 'history/event.html', context)
    model = {'person': HistoricalPerson, 'place': HistoricalPlace, 'source': HistoricalSource, 'era': HistoricalEra}[entity.kind]
    record = model.objects.get(pk=pk)
    context.update(record=record, related=[n for n in graph['nodes'] if n['id'] != pk])
    if entity.kind == 'person':
        context['role_history'] = supported_links.filter(from_entity=entity, to_entity__kind='event').order_by(
            'to_entity__historicalevent__year_order', 'to_entity_id', 'pk')
    if entity.kind == 'place':
        context['place_history'] = supported_links.filter(from_entity__kind='event', to_entity=entity).order_by(
            'from_entity__historicalevent__year_order', 'from_entity_id', 'pk')
    if entity.kind == 'source':
        context['chunks'] = record.chunks.all()[:30] if record.is_approved and not record.is_demo else []
        context['source_claims'] = public_claims().filter(evidence__source=record).distinct() if record.is_approved and not record.is_demo else []
    if entity.kind == 'era':
        context['era_events'] = HistoricalEvent.objects.visible().filter(era=record)
    return render(request, 'history/entity.html', context)

def search(request):
    query = request.GET.get('q', '')[:200]
    results = search_entities(query) if query else list(Entity.objects.visible())
    kind = request.GET.get('kind')
    if kind:
        results = [r for r in results if r.kind == kind]
    if query and request.user.is_authenticated:
        SearchHistory.objects.create(user=request.user, query=query)
    return render(request, 'history/search.html', {'query': query, 'page': Paginator(results, 24).get_page(request.GET.get('page'))})

@login_required
def library(request):
    return render(request, 'history/library.html', {
        'bookmarks': Bookmark.objects.filter(user=request.user, entity__in=Entity.objects.visible()).select_related('entity'),
        'recent': ExplorationHistory.objects.filter(user=request.user, entity__in=Entity.objects.visible()).select_related('entity')[:30],
        'searches': SearchHistory.objects.filter(user=request.user)[:12],
    })

def source_download(request, pk):
    source = get_object_or_404(HistoricalSource, pk=pk)
    if not is_admin(request.user) and (not source.is_approved or not Entity.objects.visible().filter(pk=pk).exists() or source.is_demo):
        raise Http404()
    if not source.file:
        raise Http404()
    response = FileResponse(source.file.open('rb'), as_attachment=True, filename=source.file.name.split('/')[-1], content_type='application/octet-stream')
    response['X-Content-Type-Options'] = 'nosniff'
    return response

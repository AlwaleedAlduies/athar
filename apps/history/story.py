from django.core.exceptions import ValidationError
from django.db.models import Count, F, Q
from apps.knowledge.selectors import approved_evidence, trace_claim
from .models import Entity, StoryPassage, Status


def validate_citations(passage, citations):
    citations = list(citations)
    if any(c.event_id != passage.event_id for c in citations):
        raise ValidationError('كل استشهاد في الفقرة يجب أن يخص الحدث نفسه.')
    if passage.status in [Status.APPROVED, Status.PUBLISHED]:
        available = set(approved_evidence().filter(claim__in=citations).values_list('claim_id', flat=True))
        if not citations or any(c.pk not in available for c in citations):
            raise ValidationError('نشر الفقرة يتطلب أدلة متاحة من مصادر معتمدة لكل استشهاد.')


def public_passages():
    supported = approved_evidence().values('claim_id')
    return StoryPassage.objects.filter(status__in=[Status.APPROVED, Status.PUBLISHED], event__in=Entity.objects.visible()).annotate(
        total=Count('citations', distinct=True),
        available=Count('citations', filter=Q(citations__in=supported, citations__event_id=F('event_id')), distinct=True)
    ).filter(total__gt=0, total=F('available')).prefetch_related('citations').select_related('event')


def passage_trace(passage):
    return {'id': passage.pk, 'chapter': passage.chapter, 'text': passage.text,
        'claims': [trace_claim(c) for c in passage.citations.all()], 'event_url': passage.event.get_absolute_url()}


def sync_story_references(passage):
    """Keep discovery links in step with reviewed prose; roles retain their own review."""
    if passage.status not in [Status.APPROVED, Status.PUBLISHED]:
        return
    validate_citations(passage, passage.citations.all())
    evidence = approved_evidence().filter(claim__in=passage.citations.all())
    passage.event.sources.add(*evidence.values_list('source_id', flat=True).distinct())
    visible = Entity.objects.visible()
    passage.event.persons.add(*visible.filter(pk__in=passage.citations.values('person_id')).values_list('pk', flat=True))
    passage.event.places.add(*visible.filter(pk__in=passage.citations.values('place_id')).values_list('pk', flat=True))

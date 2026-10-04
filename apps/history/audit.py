"""Read-only structural checks; source interpretation still requires editorial review."""
from django.core.exceptions import ValidationError
from django.utils import timezone
from apps.knowledge.models import Evidence
from apps.knowledge.selectors import approved_evidence, public_claims, public_relationships
from .models import HistoricalEvent, Status
from .story import public_passages


def audit_content():
    report = {'checked_at': timezone.now().isoformat(), 'scope': 'public events only',
              'method': 'Structural integrity and reading depth, not an assertion of exhaustive historical coverage.',
              'events': [], 'issues': []}
    for event in HistoricalEvent.objects.visible():
        passages = list(public_passages().filter(event=event))
        declared = event.story_passages.filter(status__in=[Status.PUBLISHED, Status.APPROVED]).count()
        proofs = approved_evidence().filter(claim__event=event)
        links = public_relationships().filter(supporting_claim__isnull=False)
        people = event.persons.visible()
        places = event.places.visible()
        missing_roles = list(people.exclude(pk__in=links.filter(to_entity=event).values('from_entity_id')).values_list('slug', flat=True))
        missing_places = list(places.exclude(pk__in=links.filter(from_entity=event).values('to_entity_id')).values_list('slug', flat=True))
        missing_sources = list(proofs.exclude(source__in=event.sources.all()).values_list('source__slug', flat=True).distinct())
        unavailable_claims = public_claims().filter(event=event).exclude(pk__in=proofs.values('claim_id')).count()
        row = {'id': event.pk, 'slug': event.slug, 'title': event.title, 'passages': len(passages),
               'chapters': len({p.chapter for p in passages}), 'words': sum(len(p.text.split()) for p in passages),
               'sources': event.sources.visible().filter(is_approved=True, is_demo=False).count(),
               'people': people.count(), 'places': places.count(), 'missing_roles': missing_roles,
               'missing_place_evidence': missing_places, 'unlinked_evidence_sources': missing_sources,
               'hidden_published_passages': declared - len(passages), 'claims_without_public_evidence': unavailable_claims}
        report['events'].append(row)
        for key in ['missing_roles', 'missing_place_evidence', 'unlinked_evidence_sources', 'hidden_published_passages', 'claims_without_public_evidence']:
            if row[key]: report['issues'].append({'event': event.slug, 'check': key, 'value': row[key]})
        if row['words'] < 350 or row['chapters'] < 3 or row['sources'] < 2:
            report['issues'].append({'event': event.slug, 'check': 'reading_depth', 'value': 'Needs a fuller multi-source narrative.'})
        for proof in Evidence.objects.filter(pk__in=proofs.values('pk')):
            try:
                proof.full_clean()
            except ValidationError as error:
                report['issues'].append({'event': event.slug, 'check': 'invalid_evidence', 'id': proof.pk, 'value': error.messages})
        for link in links.filter(supporting_claim__event=event):
            try:
                link.full_clean()
            except ValidationError as error:
                report['issues'].append({'event': event.slug, 'check': 'invalid_relationship', 'id': link.pk, 'value': error.messages})
    report['totals'] = {key: sum(row[key] for row in report['events']) for key in ['passages', 'chapters', 'words']}
    report['totals']['events'] = len(report['events'])
    return report

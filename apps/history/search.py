import re
import os
from difflib import SequenceMatcher
from .models import Entity

def normalize(text):
    text = re.sub(r'[\u064b-\u065f\u0670\u0640]', '', text.lower())
    return re.sub(r'[^\w\s]', ' ', text.translate(str.maketrans('أإآٱى', 'ااااي'))).strip()

def tokens(text):
    stop = {'ما', 'من', 'في', 'عن', 'على', 'الى', 'هذا', 'هذه', 'كان', 'لماذا', 'كيف', 'هو', 'هي', 'هل', 'الحدث', 'ماذا'}
    return {t for t in normalize(text).split() if len(t) > 1 and t not in stop}

def search_entities(query, queryset=None, semantic=True):
    queryset = queryset if queryset is not None else Entity.objects.visible()
    needle = normalize(query)
    if not needle:
        return []
    ranked = []
    items = list(queryset)
    semantic_scores = {}
    if semantic and os.getenv('EMBEDDING_BACKEND', 'hash') == 'ollama':
        try:
            from apps.ai.embeddings import embedding_service, similarity
            from apps.sources.models import SourceChunk
            from .models import HistoricalEvent
            engine = embedding_service()
            vector = engine.embed(query)
            for chunk in SourceChunk.objects.filter(source__is_approved=True, source__is_demo=False, source__in=Entity.objects.visible(), embedding_reference=engine.reference):
                score = similarity(vector, chunk.embedding)
                if score >= .55:
                    semantic_scores[chunk.source_id] = max(semantic_scores.get(chunk.source_id, 0), score * 20)
            for event_id, source_id in HistoricalEvent.objects.visible().filter(sources__in=semantic_scores).values_list('pk', 'sources__pk'):
                semantic_scores[event_id] = max(semantic_scores.get(event_id, 0), semantic_scores.get(source_id, 0))
        except Exception:
            semantic_scores = {}
    for item in items:
        title = normalize(item.title)
        content = normalize(item.description)
        score = 1000 if title == needle else 800 if title.startswith(needle) else 600 if needle in title else 400 if needle in content else 0
        score = max(score, 20 * min(10, len(tokens(needle) & tokens(title + ' ' + content))))
        # Ta marbuta equivalence is a secondary match, never a display rewrite.
        if not score and needle.replace('ة', 'ه') in title.replace('ة', 'ه'):
            score = 70
        if not score and SequenceMatcher(None, title, needle).ratio() > .67:
            score = 40
        score = max(score, semantic_scores.get(item.pk, 0))
        if score:
            ranked.append((score, item))
    return [item for score, item in sorted(ranked, key=lambda row: (-row[0], row[1].pk))]

import re
from pathlib import Path
from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError
from .models import HistoricalSource, SourceChunk
from .validators import validate_document
from apps.ai.embeddings import embedding_service

def extract_document(file):
    extension = Path(file.name).suffix.lower()
    file.open('rb')
    try:
        validate_document(file)
        if extension == '.txt':
            return [(None, 'نص المصدر', file.read().decode('utf-8-sig'))]
        if extension == '.pdf':
            from pypdf import PdfReader
            reader = PdfReader(file)
            if reader.is_encrypted or len(reader.pages) > 500:
                raise ValidationError('الملف مشفر أو يتجاوز ٥٠٠ صفحة.')
            return [(i + 1, '', page.extract_text() or '') for i, page in enumerate(reader.pages)]
        from docx import Document
        document = Document(file)
        parts, heading, text = [], 'نص المستند', []
        for paragraph in document.paragraphs:
            if paragraph.style.name.startswith('Heading'):
                if text:
                    parts.append((None, heading, '\n'.join(text)))
                heading, text = paragraph.text[:240], []
            else:
                text.append(paragraph.text)
        parts.append((None, heading, '\n'.join(text)))
        return parts
    finally:
        file.close()

def split_text(text, size=1400):
    text = re.sub(r'[ \t]+', ' ', text).strip()
    while text:
        end = min(len(text), size)
        if end < len(text):
            boundary = max(text.rfind('\n', 0, end), text.rfind(' ', 0, end))
            if boundary > size // 2:
                end = boundary
        chunk, text = text[:end].strip(), text[end:].strip()
        if chunk:
            yield chunk

def process_source(source):
    """Index saved text in place, or extract a file/URL for a source without chunks."""
    existing = list(source.chunks.order_by('ordinal'))
    engine = embedding_service()
    if existing:
        before = [(c.pk,c.text) for c in existing]
        for chunk in existing:
            chunk.embedding = engine.embed(chunk.text)
            chunk.embedding_reference = engine.reference
        with transaction.atomic():
            locked = HistoricalSource.objects.select_for_update().get(pk=source.pk)
            if list(locked.chunks.order_by('ordinal').values_list('pk','text')) != before:
                raise ValidationError('تغير نص المصدر أثناء المعالجة؛ أعد المحاولة.')
            SourceChunk.objects.bulk_update(existing,['embedding','embedding_reference'])
            locked.processed_at = timezone.now(); locked.save(update_fields=['processed_at'])
        return len(existing)
    final_url = source.url
    if source.file:
        pages = extract_document(source.file)
    elif source.url:
        from .web_import import fetch_page
        final_url,text = fetch_page(source.url)
        pages = [(None,'نص الصفحة',text)]
    else:
        raise ValidationError('أرفق ملفًا أو رابط صفحة، أو أضف مقاطع نصية للمصدر أولًا.')
    chunks = []
    for page, section, text in pages:
        for part in split_text(text):
            chunks.append(SourceChunk(source=source,page_number=page,section=section,ordinal=len(chunks),text=part,
                embedding=engine.embed(part),embedding_reference=engine.reference))
            if len(chunks)>3000: raise ValidationError('المصدر أكبر من الحد المسموح للمعالجة.')
    if not chunks:
        raise ValidationError('لم يُستخرج نص. ملفات PDF المصورة تحتاج إلى OCR قبل رفعها.')
    with transaction.atomic():
        locked = HistoricalSource.objects.select_for_update().get(pk=source.pk)
        if locked.chunks.exists():
            raise ValidationError('اكتملت معالجة أخرى لهذا المصدر؛ أعد تحميل الصفحة.')
        SourceChunk.objects.bulk_create(chunks)
        locked.processed_at = timezone.now(); locked.url = final_url
        locked.save(update_fields=['processed_at','url'])
    return len(chunks)

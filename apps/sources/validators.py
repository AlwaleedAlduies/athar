from pathlib import Path
from zipfile import ZipFile, BadZipFile
from django.core.exceptions import ValidationError


def validate_document(value):
    was_closed = value.closed
    if value.size > 10 * 1024 * 1024:
        raise ValidationError('الحد الأقصى لحجم الملف ١٠ ميغابايت.')
    extension = Path(value.name).suffix.lower()
    if extension not in {'.pdf', '.txt', '.docx'}:
        raise ValidationError('الأنواع المسموحة: PDF، TXT، DOCX.')
    try:
        value.seek(0)
        head = value.read(1024)
        value.seek(0)
        if extension == '.pdf' and not head.startswith(b'%PDF-'):
            raise ValueError()
        if extension == '.txt':
            text = value.read().decode('utf-8-sig')
            if '\x00' in text:
                raise ValueError()
        if extension == '.docx':
            with ZipFile(value) as archive:
                if 'word/document.xml' not in archive.namelist() or sum(i.file_size for i in archive.infolist()) > 30 * 1024 * 1024:
                    raise ValueError()
    except (ValueError, UnicodeError, BadZipFile):
        raise ValidationError('محتوى الملف لا يطابق نوعه أو تعذر قراءته.')
    finally:
        if was_closed:
            value.close()
        else:
            value.seek(0)

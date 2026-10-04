import uuid
from django import forms
from apps.history.models import HistoricalEvent, HistoricalPerson, HistoricalPlace
from apps.sources.models import HistoricalSource
from apps.sources.validators import validate_document


class ImportSourceForm(forms.Form):
    token = forms.UUIDField(widget=forms.HiddenInput, initial=uuid.uuid4)
    event = forms.ModelChoiceField(label='الحدث الذي تعمل عليه', queryset=HistoricalEvent.objects.filter(deleted_at__isnull=True))
    title = forms.CharField(label='عنوان المصدر', max_length=240, required=False)
    input_kind = forms.ChoiceField(label='من أين نقرأ؟', choices=[('url', 'رابط موقع'), ('file', 'ملف PDF / DOCX / TXT'), ('existing', 'مصدر محفوظ')], widget=forms.RadioSelect)
    url = forms.URLField(label='رابط الصفحة', max_length=2048, required=False, widget=forms.URLInput(attrs={'placeholder': 'https://...', 'dir': 'ltr'}))
    document = forms.FileField(label='الملف', required=False, validators=[validate_document], widget=forms.ClearableFileInput(attrs={'accept': '.pdf,.docx,.txt'}))
    source = forms.ModelChoiceField(label='مصدر من المكتبة', queryset=HistoricalSource.objects.filter(is_demo=False, deleted_at__isnull=True), required=False)
    focus = forms.CharField(label='ما الذي تريد استخراجه؟', max_length=800, required=False,
        widget=forms.Textarea(attrs={'rows': 3, 'placeholder': 'مثلًا: تسلسل الحدث، أدوار الشخصيات، القرارات ونتائجها…'}))

    def clean(self):
        data = super().clean()
        required = {'url': 'url', 'file': 'document', 'existing': 'source'}.get(data.get('input_kind'))
        if required and not data.get(required):
            self.add_error(required, 'أكمل هذا الحقل للنوع المختار.')
        if data.get('input_kind') != 'existing' and not data.get('title'):
            self.add_error('title', 'اكتب عنوانًا للمصدر.')
        return data


class SuggestionReviewForm(forms.Form):
    selected = forms.BooleanField(label='احفظ هذا الاقتراح كمسودة', required=False, initial=True)
    claim = forms.CharField(label='المعلومة المستخرجة', max_length=1600, widget=forms.Textarea(attrs={'rows': 3}))
    chapter = forms.CharField(label='عنوان الفصل', max_length=180)
    story = forms.CharField(label='الصياغة القصصية', max_length=5000, widget=forms.Textarea(attrs={'rows': 7}))
    classification = forms.ChoiceField(label='طبيعة المعلومة', choices=[('FACT', 'واقعة'), ('INTERPRETATION', 'تفسير'), ('MULTIPLE_ACCOUNTS', 'اختلاف روايات'), ('UNCERTAIN', 'غير محسوم')])
    person = forms.ModelChoiceField(label='الشخصية المرتبطة إن ثبتت', queryset=HistoricalPerson.objects.filter(is_demo=False, deleted_at__isnull=True), required=False)
    place = forms.ModelChoiceField(label='المكان المرتبط إن ثبت', queryset=HistoricalPlace.objects.filter(is_demo=False, deleted_at__isnull=True), required=False)
    role = forms.ChoiceField(label='علاقة الشخصية بالحدث', choices=[('RELATED_TO', 'صلة بالسياق'), ('PARTICIPATED_IN', 'شارك في'), ('NARRATED', 'روى خبر')])

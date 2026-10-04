/* Native form controls remain usable without JavaScript. Filtering never clears choices. */
document.querySelectorAll('.editor-form .form-field').forEach(field => {
  const choices = field.querySelector('#id_citations, div:has(input[type="checkbox"])');
  const select = field.querySelector('select');
  const control = choices || select;
  if (!control || (select && select.options.length < 9)) return;
  const input = document.createElement('input');
  input.type = 'search'; input.className = 'choice-search';
  input.placeholder = 'ابحث في الخيارات…';
  input.setAttribute('aria-label', 'ابحث في خيارات ' + (field.querySelector('label')?.textContent || 'الربط'));
  const normalize = text => text.normalize('NFKD').replace(/[\u064b-\u065f\u0670]/g, '').toLocaleLowerCase();
  control.before(input);
  if (choices) choices.classList.add('choice-list');
  input.addEventListener('input', () => {
    const query = normalize(input.value.trim());
    if (choices) {
      choices.querySelectorAll('label').forEach(label => {
        label.parentElement.hidden = !normalize(label.textContent).includes(query);
      });
    } else {
      [...select.options].forEach(option => { option.hidden = !option.selected && !!option.value && !normalize(option.textContent).includes(query); });
    }
  });
});

const editor = document.querySelector('.editor-form');
if (editor) {
  const source = editor.querySelector('[name="source"]');
  const chunk = editor.querySelector('select[name="source_chunk"],select[name="chunk"]');
  const event = editor.querySelector('select[name="event"]');
  const citations = editor.querySelector('#id_citations');
  let sourceRequest = 0, eventRequest = 0, loadedChunks = [];
  const feedback = document.createElement('p');
  feedback.className = 'helptext'; feedback.setAttribute('role', 'status');
  editor.querySelector('.editor-actions').before(feedback);
  const fetchItems = async (key, id) => {
    const response = await fetch(`${editor.dataset.optionsUrl}?${key}=${encodeURIComponent(id)}`, {headers: {'Accept': 'application/json'}});
    if (!response.ok) throw new Error();
    return (await response.json()).items;
  };
  if (source && chunk) {
    const copy = document.createElement('button');
    copy.type = 'button'; copy.className = 'button secondary small'; copy.textContent = 'املأ الاقتباس والموضع من المقطع';
    chunk.after(copy);
    const loadChunks = async reset => {
      const request = ++sourceRequest;
      try {
        const items = source.value ? await fetchItems('source', source.value) : [];
        if (request !== sourceRequest) return;
        loadedChunks = items;
        const selected = reset ? '' : chunk.value;
        chunk.replaceChildren(new Option('اختر المقطع', ''));
        items.forEach(item => chunk.add(new Option(item.label, item.id, false, String(item.id) === selected)));
        if (reset) feedback.textContent = 'حُدثت مقاطع المصدر. اختر المقطع ثم املأ الاقتباس؛ النص الذي كتبته يبقى حتى تستبدله بنفسك.';
      } catch { feedback.textContent = 'تعذر تحديث المقاطع. أعد تحميل الصفحة أو احفظ كمسودة ثم اختر المصدر مجددًا.'; }
    };
    source.addEventListener('change', () => loadChunks(true));
    copy.addEventListener('click', () => {
      const item = loadedChunks.find(row => String(row.id) === chunk.value);
      if (!item) { feedback.textContent = 'اختر مقطعًا أولًا.'; return; }
      const target = editor.querySelector('[name="evidence_text"],[name="quote"]');
      if (target.value.trim() && target.value !== item.text && !confirm('استبدال الاقتباس المكتوب بنص المقطع المحدد؟')) return;
      target.value = item.text;
      const page = editor.querySelector('[name="page_number"]'), section = editor.querySelector('[name="section"]');
      if (page) page.value = item.page ?? '';
      if (section) section.value = item.section;
      feedback.textContent = 'نُقل النص وموضعه إلى النموذج. راجعه ثم احفظ.';
    });
    loadChunks(false);
  }
  if (event && citations) event.addEventListener('change', async () => {
    const request = ++eventRequest;
    try {
      const items = event.value ? await fetchItems('event', event.value) : [];
      if (request !== eventRequest) return;
      citations.replaceChildren();
      items.forEach(item => {
        const row = document.createElement('div'), label = document.createElement('label'), input = document.createElement('input');
        input.type = 'checkbox'; input.name = 'citations'; input.value = item.id;
        label.append(input, document.createTextNode(item.label + ' · ' + item.status)); row.append(label); citations.append(row);
      });
      feedback.textContent = 'حُدثت الاستشهادات للحدث الجديد. اختر المعلومات الداعمة للفقرة قبل النشر.';
    } catch { feedback.textContent = 'تعذر تحديث الاستشهادات. أعد تحميل الصفحة؛ سيمنع الحفظ ربط فقرة بأدلة حدث آخر.'; }
  });
}

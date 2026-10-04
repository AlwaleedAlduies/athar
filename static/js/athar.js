/* ATHAR: progressive enhancement; content and navigation remain server rendered. */
(() => {
  'use strict';
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));
  const kindLabels = {event: 'حدث', person: 'شخصية', place: 'مكان', source: 'مصدر', era: 'حقبة'};
  const make = (tag, text, className) => {
    const element = document.createElement(tag);
    if (text !== undefined) element.textContent = text;
    if (className) element.className = className;
    return element;
  };
  let toastTimer;
  function toast(message) {
    const box = $('#toast');
    box.textContent = message;
    box.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { box.hidden = true; }, 4500);
  }
  function flattenError(value) {
    if (typeof value === 'string') return value;
    if (Array.isArray(value)) return value.map(flattenError).join(' ');
    if (value && typeof value === 'object') return Object.values(value).map(flattenError).join(' ');
    return 'تعذر إتمام هذه الخطوة.';
  }
  async function api(url, options = {}) {
    const csrfCookie = document.cookie.split('; ').find(value => value.startsWith('csrftoken='));
    const csrf = csrfCookie ? decodeURIComponent(csrfCookie.slice('csrftoken='.length)) : ($('[name=csrfmiddlewaretoken]')?.value || '');
    const response = await fetch(url, {credentials: 'same-origin', ...options,
      headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf, ...(options.headers || {})}});
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      if (response.status === 403 && url.includes('bookmarks')) throw new Error('سجّل الدخول لحفظ هذه المحطة في رحلتك.');
      if (response.status === 429) throw new Error('توقّف قليلًا؛ تجاوزت عدد الأسئلة المتاح. حاول لاحقًا.');
      throw new Error(flattenError(data.error || data.detail || 'تعذر إتمام هذه الخطوة. حاول مجددًا.'));
    }
    return data;
  }
  function busy(button, label) {
    const previous = button.textContent;
    button.disabled = true;
    button.textContent = label;
    return () => { button.disabled = false; button.textContent = previous; };
  }

  $$('[data-bookmark]').forEach(button => button.addEventListener('click', async () => {
    const restore = busy(button, 'نحفظ هذه المحطة...');
    try {
      const result = await api('/api/v1/bookmarks/toggle/', {method: 'POST', body: JSON.stringify({entity: Number(button.dataset.bookmark)})});
      restore();
      button.textContent = result.saved ? 'محفوظ في رحلتي' : 'احفظ في رحلتي';
      button.setAttribute('aria-pressed', String(result.saved));
      toast(result.saved ? 'أُضيفت هذه المحطة إلى رحلتك.' : 'أُزيلت من المحفوظات.');
    } catch (error) { restore(); toast(error.message); }
  }));

  function activateTab(name, updateHash = true) {
    const panel = $(`#${name}-panel`);
    if (!panel) return;
    $$('.tab-panel').forEach(p => { p.hidden = p !== panel; });
    $$('.event-tabs [role=tab]').forEach(tab => {
      const active = tab.dataset.tab === name;
      tab.setAttribute('aria-selected', String(active));
      tab.tabIndex = active ? 0 : -1;
    });
    if (updateHash) history.replaceState(null, '', `#${name}`);
    if (name === 'graph') drawGraph();
  }
  $$('[data-tab]').forEach(button => button.addEventListener('click', () => activateTab(button.dataset.tab)));
  const tabs = $$('.event-tabs [role=tab]');
  tabs.forEach((tab, index) => tab.addEventListener('keydown', event => {
    let next;
    if (event.key === 'ArrowLeft') next = (index + 1) % tabs.length;
    if (event.key === 'ArrowRight') next = (index + tabs.length - 1) % tabs.length;
    if (event.key === 'Home') next = 0;
    if (event.key === 'End') next = tabs.length - 1;
    if (next !== undefined) { event.preventDefault(); tabs[next].focus(); activateTab(tabs[next].dataset.tab); }
  }));
  if (tabs.length) activateTab(location.hash.slice(1) || 'overview', false);

  const dialog = $('#evidence-dialog');
  let traceOrigin;
  async function trace(id, origin) {
    traceOrigin = origin;
    const content = $('#evidence-content');
    content.replaceChildren(make('p', 'نتتبع أثر المعلومة...', 'muted'));
    if (!dialog.open) dialog.showModal();
    try {
      const data = await api(`/api/v1/claims/${id}/evidence/`);
      content.replaceChildren();
      content.append(make('span', data.confidence, 'badge interpretation'), make('h3', 'الادعاء'), make('p', data.claim));
      const details = make('dl', undefined, 'metadata');
      [['التصنيف', data.classification], ['حالة المراجعة', data.review_status], ['السياق', data.context]].forEach(([label, text]) => details.append(make('dt', label), make('dd', text)));
      content.append(details);
      if (!data.evidence.length) content.append(make('p', 'لم نعثر في المصادر المعتمدة حاليًا على دليل كافٍ. لا يُعامل هذا النص بوصفه حقيقة موثقة.', 'notice'));
      data.evidence.forEach(item => {
        const box = make('article', undefined, 'evidence-block');
        const link = make('a', item.source_title); link.href = item.source_url;
        box.append(make('span', item.support, 'badge neutral'), make('blockquote', item.text), link,
          make('small', item.page ? `صفحة ${item.page} · ${item.section}` : `${item.section || 'موضع غير محدد'} · رقم الصفحة غير متاح`));
        if (item.notes) box.append(make('p', item.notes));
        if (item.reference) {
          const reference = make('details', undefined, 'evidence-reference');
          reference.append(make('summary', 'بيانات الرواية والمصدر'), make('p', item.reference));
          box.append(reference);
        }
        if (item.original_url && /^https?:\/\//i.test(item.original_url)) {
          const original = make('a', 'اقرأ السياق في المصدر الأصلي ↗', 'text-link');
          original.href = item.original_url; original.target = '_blank'; original.rel = 'noopener noreferrer'; box.append(original);
        }
        content.append(box);
      });
      if (data.other_accounts.length) {
        content.append(make('h3', 'اختلافات أخرى في هذا الحدث'));
        data.other_accounts.forEach(account => content.append(make('p', account.claim_text)));
      }
    } catch (error) { content.replaceChildren(make('p', error.message, 'notice')); }
  }
  $$('[data-trace]').forEach(button => button.addEventListener('click', () => trace(button.dataset.trace, button)));
  async function storyTrace(id, origin) {
    traceOrigin = origin;
    const content = $('#evidence-content');
    content.replaceChildren(make('p', 'نفتح استشهاد الفقرة…', 'muted'));
    if (!dialog.open) dialog.showModal();
    try {
      const data = await api(`/api/v1/passages/${id}/citations/`);
      content.replaceChildren(make('span', 'السرد ومصادره', 'badge interpretation'), make('h3', data.chapter), make('p', data.text, 'cited-passage'));
      const seen = new Set();
      data.claims.forEach(claim => {
        if (claim.classification.includes('روايات')) content.append(make('p', 'توجد روايات متعددة في هذه الفقرة؛ راجع تفاصيل الخلاف في المصدر.', 'notice compact'));
        claim.evidence.forEach(item => {
          const key = `${item.source_id}:${item.chunk_id}:${item.text}`;
          if (seen.has(key)) return;
          seen.add(key);
          const box = make('article', undefined, 'evidence-block');
          const source = make('a', item.source_title, 'story-source-title'); source.href = item.source_url;
          box.append(source, make('small', item.page ? `صفحة ${item.page} · ${item.section}` : item.section || 'موضع في المصدر'), make('blockquote', item.text));
          if (item.notes) box.append(make('p', item.notes, 'small-text'));
          if (item.reference) { const details = make('details'); details.append(make('summary', 'بيانات المرجع'), make('p', item.reference)); box.append(details); }
          if (item.original_url && /^https?:\/\//i.test(item.original_url)) {
            const original = make('a', 'اقرأ الموضع في المرجع الأصلي ↗', 'text-link'); original.href = item.original_url; original.target = '_blank'; original.rel = 'noopener noreferrer'; box.append(original);
          }
          content.append(box);
        });
      });
    } catch (error) { content.replaceChildren(make('p', 'تعذر فتح استشهاد الفقرة. قد تكون أدلتها قيد المراجعة؛ حاول تحديث الصفحة.', 'notice')); }
  }
  document.addEventListener('click', event => {
    const target = event.target.closest('[data-story]');
    if (target) storyTrace(target.dataset.story, target);
  });
  $$('[data-close-dialog]').forEach(button => button.addEventListener('click', () => dialog.close()));
  dialog?.addEventListener('close', () => traceOrigin?.focus());
  dialog?.addEventListener('click', event => { if (event.target === dialog) { const rect = dialog.getBoundingClientRect(); if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) dialog.close(); } });

  const askForm = $('#ask-form');
  $$('[data-question]').forEach(button => button.addEventListener('click', () => {
    if (!askForm) return;
    $('#question').value = button.dataset.question;
    askForm.requestSubmit();
  }));
  let asking = false;
  askForm?.addEventListener('submit', async event => {
    event.preventDefault();
    if (asking) return;
    asking = true;
    const button = $('button[type=submit]', askForm);
    const restore = busy(button, 'نبحث في المصادر...');
    const output = $('#ai-answer');
    output.replaceChildren(make('p', 'نتتبع أثر المعلومة...'));
    try {
      const answer = await api('/api/v1/ai/ask/', {method: 'POST', body: JSON.stringify({question: $('#question').value, event_id: Number(askForm.dataset.event)})});
      output.replaceChildren(make('span', answer.confidence, 'badge interpretation'), make('p', answer.answer));
      if (answer.history_url) {
        const saved = make('a', 'حُفظت الإجابة — افتح سجل أسئلتي ↗', 'text-link');
        saved.href = answer.history_url; output.append(saved);
      }
      if (answer.mode === 'unavailable') {
        const localEvidence = make('a', 'راجع الأدلة المنشورة لهذا الحدث ↗', 'text-link answer-link');
        localEvidence.href = '#evidence';
        localEvidence.addEventListener('click', click => {
          click.preventDefault();
          activateTab('evidence');
          $('#evidence-tab')?.focus();
          $('#evidence-panel')?.scrollIntoView({block: 'start'});
        });
        output.append(localEvidence);
        return;
      }
      if (answer.mode === 'extractive' && answer.sources.length) output.append(make('small', 'عرض مقتطفات من المصادر، دون توليد إجابة بالذكاء الاصطناعي.'));
      if (answer.sources.length) output.append(make('h3', 'الدليل والمصدر'));
      const sourceGroups = new Map();
      answer.sources.forEach(source => {
        if (!sourceGroups.has(source.id)) sourceGroups.set(source.id, []);
        sourceGroups.get(source.id).push(source);
      });
      sourceGroups.forEach(group => {
        const source = group[0];
        const card = make('div', undefined, 'answer-source');
        const link = make('a', source.title, 'answer-link');
        link.href = source.url; card.append(link);
        const positions = [...new Set(group.map(row => [row.section, row.page ? `صفحة ${row.page}` : ''].filter(Boolean).join(' · ')).filter(Boolean))];
        if (positions.length) card.append(make('small', positions.join('؛ ')));
        const evidence = answer.evidence.find(row => row.event_id === Number(askForm.dataset.event) && group.some(chunk => chunk.chunk_id === row.chunk_id));
        if (evidence) card.append(make('p', `ارتباطه بهذا الحدث: ${evidence.claim || evidence.text}`, 'answer-context'));
        output.append(card);
      });
      const uniqueClaims = new Set();
      answer.evidence.forEach(evidence => {
        if (evidence.event_id !== Number(askForm.dataset.event)) return;
        if (uniqueClaims.has(evidence.claim_id)) return;
        uniqueClaims.add(evidence.claim_id);
        const claimTitle = evidence.claim || evidence.text;
        const label = claimTitle.length > 110 ? claimTitle.slice(0, 110) + '…' : claimTitle;
        const traceButton = make('button', `دليل: ${label} ↗`, 'text-link answer-link');
        traceButton.type = 'button';
        traceButton.addEventListener('click', () => trace(evidence.claim_id, traceButton));
        output.append(traceButton);
      });
      answer.related_entities.forEach(entity => {
        const link = make('a', `واصل الرحلة: ${entity.title}`, 'answer-link'); link.href = entity.url; output.append(link);
      });
    } catch (error) { output.replaceChildren(make('p', error.message, 'notice')); }
    finally { restore(); asking = false; }
  });

  function drawGraph() {
    const dataElement = $('#graph-data');
    if (!dataElement) return;
    const data = JSON.parse(dataElement.textContent);
    const enabled = new Set($$('.graph-filters input:checked').map(input => input.value));
    const nodes = data.nodes.filter(node => node.id === data.center || enabled.has(node.kind));
    const center = nodes.find(node => node.id === data.center);
    const other = nodes.filter(node => node.id !== data.center);
    const dense = other.length > 9;
    const graphHeight = dense ? Math.max(550, Math.ceil(other.length / 2) * 100 + 80) : 550;
    const positions = new Map([[data.center, {x: 500, y: graphHeight / 2}]]);
    other.forEach((node, index) => {
      if (dense) {
        positions.set(node.id, {x: index % 2 ? 825 : 175, y: 80 + Math.floor(index / 2) * 100});
        return;
      }
      const angle = -Math.PI / 2 + index * 2 * Math.PI / Math.max(other.length, 1);
      positions.set(node.id, {x: 500 + 340 * Math.cos(angle), y: 275 + 220 * Math.sin(angle)});
    });
    const svg = $('#graph-lines'); const nodeBox = $('#graph-nodes'); const legend = $('#graph-legend');
    if (!svg || !nodeBox) return;
    svg.setAttribute('viewBox', `0 0 1000 ${graphHeight}`);
    $('#graph-canvas').style.setProperty('--graph-height', `${graphHeight}px`);
    svg.replaceChildren(); nodeBox.replaceChildren(); legend.replaceChildren();
    svg.setAttribute('preserveAspectRatio', 'none');
    data.edges.filter(edge => positions.has(edge.source) && positions.has(edge.target)).forEach(edge => {
      const a = positions.get(edge.source), b = positions.get(edge.target);
      const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
      Object.entries({x1:1000-a.x, y1:a.y, x2:1000-b.x, y2:b.y}).forEach(([key,value]) => line.setAttribute(key, value));
      const label = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      label.setAttribute('x', 1000-(a.x+b.x)/2); label.setAttribute('y', (a.y+b.y)/2-7); label.textContent = edge.label;
      if (dense) { const title = document.createElementNS('http://www.w3.org/2000/svg', 'title'); title.textContent = edge.label; line.append(title); svg.append(line); }
      else svg.append(line,label);
    });
    nodes.forEach(node => {
      const p = positions.get(node.id);
      const link = make('a', node.title, `graph-node kind-${node.kind}${node.id === data.center ? ' center' : ''}`);
      link.href = node.url; link.style.right = `${p.x/10}%`; link.style.top = `${p.y/graphHeight*100}%`;
      link.append(make('small', kindLabels[node.kind]));
      nodeBox.append(link);
      if (node.id !== center?.id) { const listLink = make('a', `${kindLabels[node.kind]}: ${node.title}`); listLink.href = node.url; legend.append(listLink); }
    });
    if (!other.length) legend.append(make('p', 'لا توجد روابط معتمدة تطابق هذا الاختيار.', 'muted'));
  }
  $$('.graph-filters input').forEach(input => input.addEventListener('change', drawGraph));
  $('#reset-graph')?.addEventListener('click', () => { $$('.graph-filters input').forEach(input => {input.checked = true;}); drawGraph(); });
  drawGraph();

  $$('.simulation-form').forEach(form => form.addEventListener('submit', async event => {
    event.preventDefault();
    if (!$('[name=acknowledged]', form).checked) return;
    const restore = busy($('button[type=submit]', form), 'نتأمل البدائل...');
    const output = $('.simulation-result', form);
    output.replaceChildren(make('p', 'نعدّ النشاط التعليمي...'));
    try {
      const result = await api(`/api/v1/simulations/${form.dataset.scenario}/run/`, {method:'POST', body:JSON.stringify({acknowledged:true, choice:$('[name=choice]', form).value})});
      output.replaceChildren(make('span', 'محاكاة تعليمية · ليست حدثًا تاريخيًا', 'badge simulation'), make('p', result.mode, 'muted'));
      [['السياق التاريخي المتاح', result.historical_context], ['نقطة القرار', result.decision_point], ['البديل الافتراضي', result.alternative], ['النتائج المحتملة', result.possible_consequences], ['العوامل المؤثرة', result.influencing_factors]].forEach(([label,text]) => output.append(make('h3', label), make('p', text)));
    } catch (error) { output.replaceChildren(make('p', error.message, 'notice')); }
    finally { restore(); }
  }));
  $$('form[data-confirm]').forEach(form => form.addEventListener('submit', event => { if (!confirm(form.dataset.confirm)) event.preventDefault(); }));
  $$('[data-busy-form]').forEach(form => form.addEventListener('submit', event => {
    const button = event.submitter || $('button[type=submit]', form);
    if (button?.name) {
      const hidden = document.createElement('input'); hidden.type = 'hidden'; hidden.name = button.name;
      hidden.value = button.value; hidden.dataset.submitValue = 'true'; form.append(hidden);
    }
    form.setAttribute('aria-busy', 'true');
    $$('button[type=submit]', form).forEach(item => { item.dataset.originalLabel = item.textContent; item.disabled = true; });
    if (button) button.textContent = button.dataset.busyLabel || 'جارٍ الحفظ…';
  }));
  function selectImportKind() {
    const kind = $('[name=input_kind]:checked')?.value;
    if (kind) $$('[data-input-kind]').forEach(field => { field.hidden = field.dataset.inputKind !== kind; });
  }
  $$('[name=input_kind]').forEach(input => input.addEventListener('change', selectImportKind));
  selectImportKind();
  window.addEventListener('pageshow', event => { if (event.persisted) $$('[data-busy-form]').forEach(form => {
    form.removeAttribute('aria-busy'); $$('[data-submit-value]', form).forEach(item => item.remove());
    $$('button[type=submit]', form).forEach(button => { button.disabled = false; if (button.dataset.originalLabel) button.textContent = button.dataset.originalLabel; });
  }); });
  $$('.entity-decision').forEach(grid => {
    const action = $('select[name$="-action"]', grid);
    const update = () => $$('.form-field', grid).forEach(field => {
      const input = $('input,select,textarea', field); if (!input || input === action) return;
      const link = input.name.endsWith('-entity'); field.hidden = link ? action.value !== 'link' : action.value !== 'create';
    });
    action?.addEventListener('change', update); if (action) update();
  });
  const analysis = $('[data-analysis-status]');
  if (analysis) {
    let errors = 0;
    const poll = async () => {
      try {
        const result = await api(analysis.dataset.analysisStatus);
        $('#analysis-label').textContent = result.label;
        $('#analysis-count').textContent = `${result.processed} / ${result.total} مقاطع`;
        $('#analysis-progress').value = result.progress;
        $('#analysis-feedback').textContent = `${result.entities} أسماء مسندة · ${result.remaining} مقاطع متبقية`;
        if (!['QUEUED','RUNNING'].includes(result.status)) { location.reload(); return; }
        if (result.status === 'RUNNING' && result.can_retry) { location.reload(); return; }
        errors = 0;
      } catch (_) {
        errors += 1;
        if (errors >= 3) { $('#analysis-feedback').textContent = 'تعذر تحديث التقدم. أعد تحميل الصفحة للتحقق من حالة التحليل.'; return; }
      }
      window.setTimeout(poll, 4000);
    };
    window.setTimeout(poll, 2500);
  }
})();

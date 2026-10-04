(() => {
  'use strict';
  const root = document.querySelector('#journey');
  if (!root) return;
  const stations = JSON.parse(document.querySelector('#journey-data').textContent);
  if (!stations.length) return;
  const $ = id => document.getElementById(id);
  const chapters = ['scene', 'context', 'evidence'];
  const numerals = new Intl.NumberFormat('ar');
  let index = 0, chapter = 'scene', firstRender = true;
  const prefersReduced = window.matchMedia('(prefers-reduced-motion: reduce)');
  let reduced = false;
  try { reduced = localStorage.getItem('athar-reduced-motion') === 'true'; } catch (_) { /* Storage may be disabled. */ }
  const isReduced = () => reduced || prefersReduced.matches;
  function syncMotion() {
    document.documentElement.classList.toggle('reduce-motion', isReduced());
    if (isReduced()) document.getAnimations().forEach(animation => animation.cancel());
    $('motion-toggle').setAttribute('aria-pressed', String(isReduced()));
    $('motion-toggle').textContent = isReduced() ? 'الحركة مخفّضة' : 'تقليل الحركة';
    $('motion-toggle').disabled = prefersReduced.matches;
    $('motion-toggle').title = prefersReduced.matches ? 'تقليل الحركة مفعّل في إعدادات جهازك' : '';
  }
  $('motion-toggle').addEventListener('click', () => {
    reduced = !isReduced();
    try { localStorage.setItem('athar-reduced-motion', String(reduced)); } catch (_) { /* Optional preference. */ }
    syncMotion();
  });
  prefersReduced.addEventListener('change', syncMotion);
  syncMotion();
  function link(title, href) {
    const a = document.createElement('a'); a.textContent = title; a.href = href;
    return a;
  }
  const rail = $('station-rail');
  stations.forEach((station, position) => {
    const button = document.createElement('button'); button.type = 'button';
    const number = document.createElement('span'); number.className = 'rail-number'; number.textContent = String(position + 1).padStart(2, '0');
    const text = document.createElement('span'), title = document.createElement('strong'), date = document.createElement('small');
    title.textContent = station.title; date.textContent = station.date; text.append(date, title);
    const arrow = document.createElement('span'); arrow.className = 'rail-arrow'; arrow.textContent = '↗'; arrow.setAttribute('aria-hidden', 'true');
    button.append(number, text, arrow); button.addEventListener('click', () => navigate(position, 'scene'));
    rail.append(button);
  });
  function navigate(nextIndex, nextChapter = chapter) {
    if (nextIndex < 0 || nextIndex >= stations.length) return;
    const hash = `event=${stations[nextIndex].id}&chapter=${nextChapter}`;
    if (location.hash.slice(1) === hash) return;
    location.hash = hash;
  }
  function readLocation() {
    const params = new URLSearchParams(location.hash.slice(1));
    const found = stations.findIndex(station => String(station.id) === params.get('event'));
    const oldIndex = index; index = found < 0 ? 0 : found;
    chapter = chapters.includes(params.get('chapter')) ? params.get('chapter') : 'scene';
    render(firstRender || oldIndex !== index);
  }
  function animate(el, frames, duration, delay = 0) {
    if (isReduced() || !el.animate) return;
    el.getAnimations().forEach(animation => animation.cancel());
    el.animate(frames, {duration, delay, easing: 'cubic-bezier(.16,1,.3,1)', fill: 'backwards'});
  }
  function render(stationChanged) {
    const station = stations[index], last = index === stations.length - 1;
    root.dataset.tone = station.tone;
    $('station-kicker').textContent = `${station.type}${station.era ? ' / ' + station.era : ''}`;
    $('station-title').textContent = station.title;
    $('station-date').textContent = [station.date, station.gregorian, station.place].filter(Boolean).join(' · ');
    $('orbit-era').textContent = station.era || 'محطة في التاريخ';
    $('orbit-year').textContent = station.year === null ? '—' : numerals.format(station.year);
    $('orbit-date').textContent = station.date;
    $('orbit-precision').textContent = station.precision;
    $('orbit-place').textContent = station.place || 'لم يُحدد بعد';
    $('orbit-person').textContent = station.people[0]?.title || 'استكشف العلاقات';
    $('orbit-person-link').href = station.people[0] ? `/explore/${station.people[0].id}/` : station.url + '#graph';
    $('orbit-source').textContent = station.sources.length ? 'تتبّع المصادر المعتمدة' : 'الدليل ينتظر التوثيق';
    $('orbit-source-link').href = station.url + '#evidence';
    $('journey-count').textContent = `المحطة ${numerals.format(index + 1)} من ${numerals.format(stations.length)}`;
    $('journey-progress-text').textContent = `${String(index + 1).padStart(2, '0')} / ${String(stations.length).padStart(2, '0')}`;
    const progress = Math.round(((index * 3 + chapters.indexOf(chapter) + 1) / (stations.length * 3)) * 100);
    const progressbar = root.querySelector('[role="progressbar"]');
    progressbar.setAttribute('aria-valuenow', progress);
    progressbar.setAttribute('aria-valuetext', `${$('journey-count').textContent}، فصل ${chapters.indexOf(chapter) + 1} من 3`);
    progressbar.firstElementChild.style.width = `${progress}%`;
    $('station-prev').disabled = index === 0;
    $('station-next').disabled = last;
    $('journey-restart').hidden = !last;
    $('next-station-hint').textContent = last ? 'نهاية المسار… وبداية أسئلة جديدة.' : `في الأفق: ${stations[index + 1].title}`;
    $('journey-disclosure').hidden = !station.demo;
    $('journey-reference').replaceChildren();
    $('journey-reference').hidden = !station.sources.length;
    if (station.sources.length) {
      $('journey-reference').append(station.story?.length ? 'سرد يستند إلى ' : 'ملخص تحريري يستند إلى ', link(`${station.sources.length} مراجع لهذه المحطة`, station.url + '#evidence'));
    }
    $('chapter-links').replaceChildren();
    let heading, copy, destination = '';
    if (chapter === 'scene') {
      heading = 'بين يديك المشهد'; copy = station.narrative || station.description || 'لم تُضف رواية لهذا الحدث بعد.';
      station.people.forEach(person => $('chapter-links').append(link(person.title, `/explore/${person.id}/`)));
    } else if (chapter === 'context') {
      heading = 'ما الذي سبق… وما الذي بقي؟';
      copy = [station.context, station.consequences].filter(Boolean).join('\n\n') || 'ينتظر هذا الفصل إضافة السياق والنتائج الموثقة.';
      $('chapter-links').append(link('افتح شبكة العلاقات ↗', station.url + '#graph'));
    } else {
      heading = 'كل معرفة تبدأ بسؤال عن دليلها'; destination = '#evidence';
      copy = station.sources.length ? 'ابدأ من المصادر المعتمدة المرتبطة بهذا الحدث. افتح الدليل لتقرأ الادعاءات، وتفحص مواضع الاستشهاد وحدود ما تدعمه.' : 'لا توجد مصادر معتمدة مرتبطة بهذه المحطة حتى الآن. يمكنك استكشاف البناء التجريبي، مع إبقاء السؤال مفتوحًا حتى يُراجع الدليل.';
      station.sources.forEach(source => $('chapter-links').append(link(source.title, `/explore/${source.id}/`)));
    }
    $('chapter-heading').textContent = heading;
    $('chapter-copy').replaceChildren();
    const story = station.story || [];
    if (story.length && chapter !== 'evidence') {
      const passage = chapter === 'scene' ? story[0] : story[story.length - 1];
      heading = passage.chapter;
      $('chapter-heading').textContent = heading;
      const button = document.createElement('button'); button.type = 'button'; button.className = 'journey-story-text';
      button.dataset.story = passage.id; button.textContent = passage.text; button.title = 'انقر لفتح استشهاد الفقرة';
      $('chapter-copy').append(button);
    } else $('chapter-copy').textContent = copy;
    $('station-detail').href = station.url + destination;
    $('chapter-content').setAttribute('aria-labelledby', `chapter-${chapter}`);
    document.querySelectorAll('[data-chapter]').forEach(button => {
      const active = button.dataset.chapter === chapter;
      button.setAttribute('aria-selected', String(active)); button.tabIndex = active ? 0 : -1;
    });
    Array.from(rail.children).forEach((button, position) => {
      if (position === index) button.setAttribute('aria-current', 'step'); else button.removeAttribute('aria-current');
      button.classList.toggle('is-past', position < index);
    });
    if (!firstRender) $('journey-announcement').textContent = `${$('journey-count').textContent}: ${station.title}، ${heading}`;
    animate($('chapter-content'), [{opacity: 0, transform: 'translateY(14px)'}, {opacity: 1, transform: 'translateY(0)'}], 520);
    if (stationChanged) {
      animate($('station-title'), [{opacity: 0, transform: 'translateX(24px)', filter: 'blur(4px)'}, {opacity: 1, transform: 'translateX(0)', filter: 'blur(0)'}], 700);
      animate($('orbit-year'), [{opacity: 0, transform: 'translateY(30px) scale(.9)'}, {opacity: 1, transform: 'translateY(0) scale(1)'}], 950);
      animate(root.querySelector('.orbit-trail'), [{strokeDasharray: '1', strokeDashoffset: '1'}, {strokeDasharray: '1', strokeDashoffset: '0'}], 1400);
      root.querySelectorAll('.orbit-note').forEach((note, i) => animate(note, [{opacity: 0, transform: 'translateY(12px)'}, {opacity: 1, transform: 'translateY(0)'}], 600, 100 + i * 100));
    }
    if (!firstRender && stationChanged && matchMedia('(max-width:640px)').matches) {
      root.scrollIntoView({behavior:isReduced() ? 'instant' : 'smooth', block:'start'});
    }
    firstRender = false;
  }
  $('station-prev').addEventListener('click', () => navigate(index - 1, 'scene'));
  $('station-next').addEventListener('click', () => navigate(index + 1, 'scene'));
  $('journey-restart').addEventListener('click', () => navigate(0, 'scene'));
  document.querySelectorAll('[data-chapter]').forEach(button => {
    button.addEventListener('click', () => navigate(index, button.dataset.chapter));
    button.addEventListener('keydown', event => {
      if (!['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return;
      event.preventDefault(); event.stopPropagation();
      const current = chapters.indexOf(chapter);
      const next = event.key === 'Home' ? 0 : event.key === 'End' ? 2 : (current + (event.key === 'ArrowLeft' ? 1 : 2)) % 3;
      $(`chapter-${chapters[next]}`).focus(); navigate(index, chapters[next]);
    });
  });
  root.addEventListener('keydown', event => {
    if (event.altKey || event.ctrlKey || event.metaKey || /INPUT|TEXTAREA|SELECT/.test(event.target.tagName)) return;
    if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
      event.preventDefault(); navigate(index + (event.key === 'ArrowLeft' ? 1 : -1), 'scene');
    }
  });
  window.addEventListener('hashchange', readLocation);
  readLocation();
})();

(() => {
  'use strict';
  const preference = matchMedia('(prefers-reduced-motion: reduce)');
  try { if (localStorage.getItem('athar-reduced-motion') === 'true') document.documentElement.classList.add('reduce-motion'); } catch (_) { /* Optional preference. */ }
  const reduced = () => preference.matches || document.documentElement.classList.contains('reduce-motion');
  preference.addEventListener('change', () => {
    if (reduced()) document.getAnimations().forEach(animation => animation.cancel());
  });
  // Progressive enhancement: content is hidden only once an observer exists.
  if ('IntersectionObserver' in window && !reduced()) {
    const observer = new IntersectionObserver(entries => {
      entries.forEach(entry => {
        if (!entry.isIntersecting) return;
        entry.target.classList.remove('reveal-pending');
        entry.target.classList.add('reveal-visible', 'is-in-view');
        observer.unobserve(entry.target);
      });
    }, {threshold: .08, rootMargin: '0px 0px -18px 0px'});
    document.querySelectorAll('.section-heading,.event-grid>.event-card,.trust-section,.timeline-row,.event-narrative>.paper').forEach(element => {
      element.classList.add('reveal-pending'); observer.observe(element);
    });
    // Back/forward cache restores the document without waiting for a new scroll.
    window.addEventListener('pageshow', event => {
      if (event.persisted) document.querySelectorAll('.reveal-pending').forEach(el => el.classList.remove('reveal-pending'));
    });
  }
  document.querySelectorAll('.tab-panel').forEach(panel => {
    new MutationObserver(() => {
      if (panel.hidden || reduced() || !panel.animate) return;
      panel.getAnimations().forEach(animation => animation.cancel());
      panel.animate([{opacity:0,transform:'translateY(12px)'},{opacity:1,transform:'translateY(0)'}], {duration:420,easing:'cubic-bezier(.16,1,.3,1)'});
    }).observe(panel, {attributes:true,attributeFilter:['hidden']});
  });
})();

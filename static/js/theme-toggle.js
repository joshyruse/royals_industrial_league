(function(){
  const STORAGE_KEY = 'royals_theme';
  const root = document.documentElement;
  const btnMain = document.getElementById('themeToggle');
  const btnMobile = document.getElementById('themeToggleMobile');
  const navbarLogo = document.getElementById('navbarLogo');

  function setIcons(mode){
    const iMain = btnMain && btnMain.querySelector('i');
    const iMobile = btnMobile && btnMobile.querySelector('i');
    if (iMain) iMain.className = (mode === 'dark') ? 'bi bi-sun' : 'bi bi-moon-stars';
    if (iMobile) iMobile.className = (mode === 'dark') ? 'bi bi-sun me-1' : 'bi bi-moon-stars me-1';
  }

  function swapLogoWithFade(imgEl, mode) {
    if (!imgEl) return;
    const light = imgEl.getAttribute('data-logo-light');
    const dark = imgEl.getAttribute('data-logo-dark');
    const target = (mode === 'dark') ? dark : light;
    const current = imgEl.getAttribute('src');
    if (!target || current === target) return;

    const finishSwap = () => {
      imgEl.removeEventListener('transitionend', finishSwap);
      imgEl.setAttribute('src', target);
      if (imgEl.complete) {
        requestAnimationFrame(() => imgEl.classList.remove('is-fading'));
      } else {
        imgEl.onload = () => {
          imgEl.onload = null;
          imgEl.classList.remove('is-fading');
        };
      }
    };

    imgEl.addEventListener('transitionend', finishSwap, { once: true });
    imgEl.classList.add('is-fading');
    setTimeout(() => {
      if (imgEl.classList.contains('is-fading')) finishSwap();
    }, 220);
  }

  function applyTheme(mode){
    if (mode === 'dark') {
      root.setAttribute('data-theme', 'dark');
    } else {
      root.removeAttribute('data-theme');
    }
    setIcons(mode);
    if (navbarLogo) {
      swapLogoWithFade(navbarLogo, mode);
    }
  }

  const saved = localStorage.getItem(STORAGE_KEY);
  const systemDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
  const initial = saved ? saved : (systemDark ? 'dark' : 'light');
  applyTheme(initial);

  function bindToggle(el){
    if (!el) return;
    el.addEventListener('click', function(){
      const isDark = root.getAttribute('data-theme') === 'dark';
      const next = isDark ? 'light' : 'dark';
      localStorage.setItem(STORAGE_KEY, next);
      applyTheme(next);
    });
  }
  bindToggle(btnMain);
  bindToggle(btnMobile);

  // Initialize Bootstrap tooltips globally
  function initTooltips() {
    try {
      var els = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
      els.forEach(function (el) {
        if (!bootstrap.Tooltip.getInstance(el)) {
          new bootstrap.Tooltip(el, { container: 'body' });
        }
      });
    } catch (e) {
      // no-op if bootstrap is not loaded yet
    }
  }

  document.addEventListener('DOMContentLoaded', initTooltips);
  window.addEventListener('load', function(){ setTimeout(initTooltips, 0); });
  window.addEventListener('pageshow', initTooltips);
})();
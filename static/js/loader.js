(function () {
  const loader = document.getElementById('globalLoader');
  const loaderBall = document.getElementById('loaderBall');
  if (!loader || !loaderBall) return;

  const showLoader = () => {
    loader.classList.add('show');
    document.documentElement.setAttribute('aria-busy', 'true');
  };
  const hideLoader = () => {
    loader.classList.remove('show');
    document.documentElement.removeAttribute('aria-busy');
  };

  // Swap tennis ball logo when theme changes (with fade)
  const applyLoaderLogo = () => {
    const theme = document.documentElement.getAttribute('data-theme');
    const lightLogo = loaderBall.getAttribute('data-logo-light');
    const darkLogo = loaderBall.getAttribute('data-logo-dark');
    const targetSrc = theme === 'dark' ? darkLogo : lightLogo;

    const currentSrc = loaderBall.getAttribute('src');
    if (currentSrc === targetSrc) return; // already correct

    const finishSwap = () => {
      loaderBall.removeEventListener('transitionend', finishSwap);
      loaderBall.setAttribute('src', targetSrc);
      if (loaderBall.complete) {
        requestAnimationFrame(() => loaderBall.classList.remove('is-fading'));
      } else {
        loaderBall.onload = () => {
          loaderBall.onload = null;
          loaderBall.classList.remove('is-fading');
        };
      }
    };

    // Start fade-out and swap on transition end (with safety timeout)
    loaderBall.addEventListener('transitionend', finishSwap, { once: true });
    loaderBall.classList.add('is-fading');
    setTimeout(() => {
      // safety in case transitionend doesn't fire
      if (loaderBall.classList.contains('is-fading')) finishSwap();
    }, 220);
  };

  // Run once on load
  applyLoaderLogo();

  // Hook into your theme toggle (if you dispatch a custom event, reuse it)
  document.addEventListener('themeChanged', applyLoaderLogo);

  // Also detect DOM changes to data-theme
  const observer = new MutationObserver(applyLoaderLogo);
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });

  // Show on any POST form submit (long-running server work)
  document.addEventListener('submit', (e) => {
    const form = e.target;
    if (!(form instanceof HTMLFormElement)) return;
    if (form.hasAttribute('data-no-loader')) return;

    const isPost = (form.method || '').toLowerCase() === 'post';
    if (isPost || form.hasAttribute('data-show-loader')) {
      showLoader();
    }
  }, true);

  document.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-show-loader]');
    if (!btn) return;
    showLoader();
  });

  // Show loader on internal link navigations
document.addEventListener('click', (e) => {
  const a = e.target.closest('a');
  if (!a) return;

  // Ignore anything explicitly opted out
  if (a.hasAttribute('data-no-loader')) return;

  // Ignore new-window / download / modifier keys
  if (a.target === '_blank' || a.hasAttribute('download') ||
      e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) {
    return;
  }

  // Same-page anchors (hash only) shouldn't trigger loader
  const href = a.getAttribute('href') || '';
  if (href.startsWith('#')) return;

  // External links shouldn't show the app loader
  try {
    const url = new URL(a.href, window.location.href);
    const isSameOrigin = (url.origin === window.location.origin);
    if (!isSameOrigin) return;
  } catch (_) {
    // If URL parsing fails, be safe and don't show
    return;
  }

  // At this point it's an internal navigation -> show loader
  // Let the browser proceed with the navigation naturally.
  // Note: if you need to delay navigation (e.g., to run async),
  // you'd preventDefault() and manually set window.location.
  if (typeof showLoader === 'function') {
    setTimeout(() => showLoader(), 120); // small delay to prevent flicker
  }
}, true);

// Fallback: show loader on unload navigations as well
window.addEventListener('beforeunload', () => {
  if (typeof showLoader === 'function') {
    setTimeout(() => showLoader(), 120); // small delay to prevent flicker
  }
});

// Already present in your file:
// window.addEventListener('pageshow', () => hideLoader());

  window.addEventListener('pageshow', () => hideLoader());
})();

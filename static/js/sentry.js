// static/js/sentry.js
(function(){
  // Only init when DSN is provided via data attribute
  var tag = document.getElementById('sentry-init');
  if (!tag) return;
  var dsn = tag.getAttribute('data-dsn');
  if (!dsn) return;
  // Load Sentry browser SDK from jsDelivr (CSP already allows jsdelivr)
  var s = document.createElement('script');
  s.src = "https://cdn.jsdelivr.net/npm/@sentry/browser@7.120.0/build/bundle.min.js";
  s.defer = true;
  s.onload = function(){
    Sentry.init({
      dsn: dsn,
      integrations: [new Sentry.BrowserTracing()],
      tracesSampleRate: 0.0 // leave 0 unless you want front-end perf traces
    });
  };
  document.head.appendChild(s);
})();
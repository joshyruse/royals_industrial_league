// static/js/notifications_list.js
(function () {
  // ----- Select All / Indeterminate -----
  function initCheckAll() {
    var master = document.getElementById('chk-all');
    if (!master) return;

    var rows = Array.prototype.slice.call(document.querySelectorAll('.chk-row'));
    function syncMaster() {
      var total = rows.length;
      var checked = rows.filter(function (cb) { return cb.checked; }).length;
      master.indeterminate = (checked > 0 && checked < total);
      master.checked = (checked === total && total > 0);
    }

    master.addEventListener('change', function () {
      rows.forEach(function (cb) { cb.checked = master.checked; });
      syncMaster();
    }, { passive: true });

    rows.forEach(function (cb) {
      cb.addEventListener('change', syncMaster, { passive: true });
    });

    // initialize state on load
    syncMaster();
  }

  // ----- Bootstrap Toasts -----
  function initToasts() {
    var container = document.getElementById('toast-stack') || document.querySelector('.toast-container');
    if (!container || !window.bootstrap) return;

    var toasts = Array.prototype.slice.call(container.querySelectorAll('.toast'));
    toasts.forEach(function (el) {
      try {
        var inst = bootstrap.Toast.getOrCreateInstance(el, { autohide: true, delay: 3500 });
        inst.show();
      } catch (e) { /* no-op */ }
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    initCheckAll();
    initToasts();
  });
})();
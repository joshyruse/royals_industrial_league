// static/js/manage_roster.js
(function(){
  // ===== Season selection: auto-submit GET form on change =====
  var sel = document.getElementById('season-select');
  if (sel) {
    sel.addEventListener('change', function(){
      var form = sel.closest('form');
      var method = (form && form.method ? form.method : 'GET').toUpperCase();
      if (form && method === 'GET') form.submit();
    }, {passive:true});
  }

  // ===== Remove modal: populate hidden id + friendly name =====
  var removeModal = document.getElementById('removeModal');
  if (removeModal) {
    removeModal.addEventListener('show.bs.modal', function(ev){
      var btn = ev.relatedTarget; if (!btn) return;
      var idInput = document.getElementById('remove-entry-id');
      var nameOut = document.getElementById('remove-player-name');
      if (idInput) idInput.value = btn.getAttribute('data-entry-id') || '';
      if (nameOut) nameOut.textContent = btn.getAttribute('data-player-name') || 'this player';
    });
  }

  // ===== Auto-open modals when server flagged errors (via data-*) =====
  document.addEventListener('DOMContentLoaded', function(){
    if (window.bootstrap) {
      var addEl  = document.getElementById('addPlayerModal');
      if (addEl && addEl.getAttribute('data-has-errors') === '1') {
        bootstrap.Modal.getOrCreateInstance(addEl).show();
      }
      var copyEl = document.getElementById('copyRosterModal');
      if (copyEl && copyEl.getAttribute('data-has-errors') === '1') {
        bootstrap.Modal.getOrCreateInstance(copyEl).show();
      }
      // enable tooltips
      document.querySelectorAll('[data-bs-toggle="tooltip"]').forEach(function(el){
        new bootstrap.Tooltip(el, { container: 'body' });
      });
    }
  });

  // ===== Auto-submit roster limit when changed =====
  (function(){
    var input = document.getElementById('roster-limit-input');
    var form  = document.getElementById('roster-limit-form');
    if (input && form) {
      input.addEventListener('change', function(){ form.submit(); }, {passive:true});
    }

    // Submit per-row NTRP form when changed
document.addEventListener('change', function (e) {
  const sel = e.target.closest('select.js-ntrp');
  if (!sel) return;
  const form = sel.closest('form');
  if (form) form.submit();
}, { passive: true });

  })();
})();
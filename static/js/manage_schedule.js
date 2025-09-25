// static/js/manage_schedule.js
// NOTE: Any server-driven state should be passed via data-* attributes in the template.
// Example attributes to add in your template:
//  - #active-season-radio  data-active-now="true"|"false"
//  - #addModal             data-has-errors="1"   (when add_form has errors)
//  - #editModal            data-edit-fixture-id="{{ edit_fixture_id }}" (when edit form has errors)
//  - #bulkUploadModal      data-has-errors="1"   (when bulk parsing has errors)

(function(){
  // ===== Edit modal: populate fields from the trigger button =====
  var editModal = document.getElementById('editModal');
  if (editModal) {
    editModal.addEventListener('show.bs.modal', function (event) {
      var btn = event.relatedTarget;
      if (!btn) return;
      var byId = function(id){ return document.getElementById(id); };
      var v = function(el, val){ if (el) el.value = val || ''; };
      var c = function(el, bool){ if (el) el.checked = !!bool; };

      v(byId('edit-fixture-id'), btn.getAttribute('data-id'));
      v(byId('edit-week'),       btn.getAttribute('data-week'));
      v(byId('edit-date'),       btn.getAttribute('data-datetime'));
      v(byId('edit-opponent'),   btn.getAttribute('data-opponent'));
      c(byId('edit-home'),       btn.getAttribute('data-home') === 'true');

      var byeEl = byId('edit-is-bye');
      if (byeEl) byeEl.checked = (btn.getAttribute('data-bye') === 'true');
    });
  }

  // ===== Disable opponent/home inputs when BYE is toggled =====
  function bindByeToggle(modalId, byeId, opponentSelector, homeId) {
    var modal = document.getElementById(modalId);
    if (!modal) return;
    modal.addEventListener('shown.bs.modal', function(){
      var bye  = document.getElementById(byeId);
      var opp  = modal.querySelector(opponentSelector);
      var home = document.getElementById(homeId);
      function apply() {
        var checked = !!(bye && bye.checked);
        if (opp)  opp.disabled  = checked;
        if (home) home.disabled = checked;
      }
      if (bye) {
        bye.addEventListener('change', apply);
        apply();
      }
    });
  }
  bindByeToggle('addModal',  'id_is_bye',    'input[name="opponent"]', 'id_home');
  bindByeToggle('editModal', 'edit-is-bye',  '#edit-opponent',           'edit-home');

  // ===== Delete modal: pass id =====
  var deleteModal = document.getElementById('deleteModal');
  if (deleteModal) {
    deleteModal.addEventListener('show.bs.modal', function (event) {
      var btn = event.relatedTarget;
      var input = document.getElementById('delete-fixture-id');
      if (btn && input) input.value = btn.getAttribute('data-id') || '';
    });
  }

  // ===== Active season radio → confirm modal & revert if canceled =====
  (function(){
    var radio   = document.getElementById('active-season-radio');
    if (!radio) return;
    var modalEl = document.getElementById('confirmActiveModal');
    var modalInstance = null;
    var confirmed = false;
    var isActiveNow = (radio.getAttribute('data-active-now') === 'true');

    function openConfirm(){
      if (!modalEl || !window.bootstrap) return;
      confirmed = false;
      modalInstance = new bootstrap.Modal(modalEl);
      modalInstance.show();
    }

    if (modalEl) {
      var form = modalEl.querySelector('form');
      if (form) form.addEventListener('submit', function(){ confirmed = true; });
      modalEl.addEventListener('hidden.bs.modal', function(){
        if (!confirmed) radio.checked = isActiveNow; // revert to prior state
      });
    }

    radio.addEventListener('change', function(){
      if (!radio.checked) return;       // only act when checking on
      if (isActiveNow === true) return; // already active
      openConfirm();
    });
  })();

  // ===== Auto-open modals when server reported form errors (via data-*) =====
  document.addEventListener('DOMContentLoaded', function(){
    // Add form errors
    var addEl = document.getElementById('addModal');
    if (addEl && addEl.getAttribute('data-has-errors') === '1' && window.bootstrap) {
      new bootstrap.Modal(addEl).show();
    }
    // Edit form errors (requires the server to set data-edit-fixture-id)
    var editEl = document.getElementById('editModal');
    var editId = editEl ? editEl.getAttribute('data-edit-fixture-id') : null;
    if (editEl && editId && window.bootstrap) {
      var idInput = document.getElementById('edit-fixture-id');
      if (idInput) idInput.value = editId;
      new bootstrap.Modal(editEl).show();
    }
    // Bulk upload errors
    var bulkEl = document.getElementById('bulkUploadModal');
    if (bulkEl && bulkEl.getAttribute('data-has-errors') === '1' && window.bootstrap) {
      new bootstrap.Modal(bulkEl).show();
    }
  });

  // ===== Season select: submit on change, or open Create dialog =====
  (function(){
    var sel  = document.getElementById('season-select');
    if (!sel) return;
    var form = sel.closest('form');
    var lastValue = sel.value; // remember current season

    sel.addEventListener('change', function(){
      if (sel.value === '__create__') {
        // revert to last real value so dropdown doesn't stick on the special option
        sel.value = lastValue;
        var modalEl = document.getElementById('createSeasonModal');
        if (modalEl && window.bootstrap) new bootstrap.Modal(modalEl).show();
      } else {
        lastValue = sel.value;
        if (form) { form.submit(); return; }
        // Fallback if no form found
        window.location.reload();
      }
    });
  })();

  // ===== CSV example: Copy & Download =====
  (function(){
    var copyBtn = document.getElementById('copy-csv-example');
    var dlBtn   = document.getElementById('download-csv-example');
    var pre     = document.getElementById('csv-example');

    if (pre && copyBtn) {
      copyBtn.addEventListener('click', function(){
        var text = pre.innerText || pre.textContent || '';
        (async function(){
          try {
            if (navigator.clipboard && navigator.clipboard.writeText) {
              await navigator.clipboard.writeText(text);
            } else {
              var range = document.createRange();
              range.selectNodeContents(pre);
              var sel = window.getSelection();
              sel.removeAllRanges(); sel.addRange(range);
              document.execCommand('copy');
              sel.removeAllRanges();
            }
            var original = copyBtn.textContent;
            copyBtn.disabled = true; copyBtn.textContent = 'Copied!';
            setTimeout(function(){ copyBtn.disabled = false; copyBtn.textContent = original; }, 1200);
          } catch (e) {
            alert('Unable to copy. Please select and copy manually.');
          }
        })();
      });
    }

    if (pre && dlBtn) {
      dlBtn.addEventListener('click', function(){
        try {
          var text = pre.innerText || pre.textContent || '';
          var blob = new Blob([text], { type: 'text/csv;charset=utf-8;' });
          var url  = URL.createObjectURL(blob);
          var a    = document.createElement('a');
          a.href = url; a.download = 'matches_template.csv';
          document.body.appendChild(a);
          a.click();
          setTimeout(function(){ URL.revokeObjectURL(url); a.remove(); }, 0);
        } catch (e) {
          alert('Download failed. Please copy the text instead.');
        }
      });
    }
  })();

  // ===== Manage Schedule: Modal season-name sync (Delete All / Bulk Upload) =====
  (function(){
    var seasonSelect = document.getElementById('season-select');
    function currentSeasonName(){
      if (!seasonSelect) seasonSelect = document.getElementById('season-select');
      if (!seasonSelect) return '';
      var opt = seasonSelect.options[seasonSelect.selectedIndex];
      return opt ? (opt.textContent || opt.innerText).trim() : '';
    }
    function setText(id, val){
      var el = document.getElementById(id);
      if (el) el.textContent = val || '';
    }

    var deleteAll = document.getElementById('deleteAllModal');
    if (deleteAll) {
      deleteAll.addEventListener('show.bs.modal', function(){
        setText('deleteall-season-name', currentSeasonName());
      });
    }

    var bulk = document.getElementById('bulkUploadModal');
    if (bulk) {
      bulk.addEventListener('show.bs.modal', function(){
        setText('bulk-season-name', currentSeasonName());
      });
    }
  })();
})();
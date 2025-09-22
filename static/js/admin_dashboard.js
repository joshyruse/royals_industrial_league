// static/js/admin_dashboard.js

(function(){
  // ===== Admin Dashboard: Reset Season modal sync =====
  // Works only on pages that have the reset modal and a season select
  var modalEl = document.getElementById('confirmResetSeason');
  if (!modalEl) return; // not on admin dashboard

  var seasonSelect = document.getElementById('season_id');
  var form = modalEl.querySelector('form');
  var hiddenId = form ? form.querySelector('input[name="season_id"]') : null;
  var nameSlot = modalEl.querySelector('#reset-season-name');

  function currentSeasonInfo(){
    var id = seasonSelect ? seasonSelect.value : '';
    var name = '';
    if (seasonSelect) {
      var opt = seasonSelect.options[seasonSelect.selectedIndex];
      if (opt) name = (opt.textContent || opt.innerText).trim();
    }
    return { id: id, name: name };
  }

  // When the modal is about to show, copy the current dropdown selection
  modalEl.addEventListener('show.bs.modal', function(){
    var info = currentSeasonInfo();
    if (hiddenId) hiddenId.value = info.id || '';
    if (nameSlot) nameSlot.textContent = info.name || 'this season';
  });
})();
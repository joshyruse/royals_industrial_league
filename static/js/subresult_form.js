(function(){
  // Read opponent name from a data-attribute on the root form container
  // In your template (subresult_form.html), put: id="subresult-form" data-opponent="{{ fixture.opponent|default:'' }}"
  var root = document.getElementById('subresult-form') || document.body;
  var opponent = '';
  if (root) {
    opponent = root.getAttribute('data-opponent') || '';
  }

  // Auto-fill and lock team name when target is AGAINST_US
  var sel  = document.getElementById('id_target_type');
  var team = document.getElementById('id_target_team_name');
  function applyTarget(){
    if (!sel || !team) return;
    if (sel.value === 'AGAINST_US'){
      if (opponent) { team.value = opponent; }
      team.readOnly = true;
    } else {
      team.readOnly = false;
    }
  }
  if (sel){ sel.addEventListener('change', applyTarget, {passive:true}); }
  applyTarget();

  // Keep kind in sync with slot_code on the client side too
  var slot = document.getElementById('id_slot_code');
  var kind = document.getElementById('id_kind');
  function applyKind(){
    if (!slot || !kind) return;
    var v = String(slot.value || '');
    if (v.startsWith('S')){ kind.value = 'S'; }
    else if (v.startsWith('D')){ kind.value = 'D'; }
  }
  if (slot){ slot.addEventListener('change', applyKind, {passive:true}); }
  applyKind();
})();
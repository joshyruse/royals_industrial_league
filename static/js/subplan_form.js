(function(){
    const sel = document.getElementById('id_target_type');
    const team = document.getElementById('id_target_team_name');
    const hidden = document.getElementById('id_target_team_name_hidden');
    const opponent = "{{ fixture.opponent|default:'Opponent'|escapejs }}";

    function syncHidden(){
      if (hidden) hidden.value = team ? team.value : '';
    }

    function apply(){
      if (!sel || !team) return;
      if (sel.value === 'AGAINST_US'){
        if (!team.value && opponent){ team.value = opponent; }
        team.setAttribute('disabled', 'disabled');
        syncHidden();
      } else {
        team.removeAttribute('disabled');
        syncHidden();
      }
    }

    if (sel){ sel.addEventListener('change', apply); }
    if (team){ team.addEventListener('input', syncHidden); }
    // Ensure hidden has initial value and state is correct on load
    apply();

    // On submit, ensure hidden mirrors the disabled input value (defense-in-depth)
    const formEl = document.querySelector('form');
    if (formEl){
      formEl.addEventListener('submit', function(){
        if (team && team.hasAttribute('disabled')){ syncHidden(); }
      });
    }
  })();
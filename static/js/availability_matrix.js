function applyTargetTeamBehavior(){
  const sel = document.getElementById('ps-target');
  const team = document.getElementById('ps-target-team');
  if (!sel || !team) return;
  if (sel.value === 'AGAINST_US'){
    const opp = document.getElementById('fixture-opponent-name')?.dataset?.opp || 'Opponent';
    if (!team.value) team.value = opp;
    team.setAttribute('disabled','disabled');
  } else {
    team.removeAttribute('disabled');
  }
}
(function(){
  var cfgEl = document.getElementById('subplan-config');
  var actionUrl = cfgEl ? cfgEl.getAttribute('data-create-url') : null;
  const modalEl = document.getElementById('planSubModal');
  const form = document.getElementById('planSubForm');
  const btnSave = document.getElementById('ps-save');
  const errBox = document.getElementById('ps-error');
  const inputPlayer = document.getElementById('ps-player');
  const inputTimeslot = document.getElementById('ps-timeslot');
  const selectKind = document.getElementById('ps-kind');

  // Counters
  const cnt0830 = document.getElementById('cnt-0830');
  const cnt1000 = document.getElementById('cnt-1000');
  const cnt1130 = document.getElementById('cnt-1130');
  function refreshCounts(){
    const rows = document.querySelectorAll('tbody tr[data-pid]');
    let c0830=0, c1000=0, c1130=0;
    rows.forEach(r => {
      if (r.dataset.a0830 === '1') c0830++;
      if (r.dataset.a1000 === '1') c1000++;
      if (r.dataset.a1130 === '1') c1130++;
    });
    if (cnt0830) cnt0830.textContent = `(${c0830})`;
    if (cnt1000) cnt1000.textContent = `(${c1000})`;
    if (cnt1130) cnt1130.textContent = `(${c1130})`;
  }
  refreshCounts();

  function getCsrf(){
    const fromForm = form?.querySelector('input[name="csrfmiddlewaretoken"]')?.value;
    if (fromForm) return fromForm;
    const m = document.cookie.match(/csrftoken=([^;]+)/);
    return m ? m[1] : '';
  }

  if (modalEl) {
    // Prefill on click of any plan-sub link
    document.addEventListener('click', (e) => {
      const btn = e.target.closest('.plan-sub-link');
      if (!btn) return;
      if (errBox) { errBox.classList.add('d-none'); errBox.textContent = ''; }
      inputPlayer.value = btn.dataset.player;
      inputTimeslot.value = btn.dataset.timeslot;
      // Reset form fields
      const slotSel = document.getElementById('ps-slot');
      const targetSel = document.getElementById('ps-target');
      const targetTeam = document.getElementById('ps-target-team');
      const notes = document.getElementById('ps-notes');
      if (slotSel) slotSel.value = '';
      if (targetSel) targetSel.value = 'OTHER_TEAM';
      if (targetTeam) { targetTeam.value = ''; targetTeam.removeAttribute('disabled'); }
      if (notes) notes.value = '';
      // Apply target auto behavior
      applyTargetTeamBehavior();
      // Allow Bootstrap data attributes to open the modal automatically
    });

    const targetSel = document.getElementById('ps-target');
    if (targetSel) targetSel.addEventListener('change', applyTargetTeamBehavior);

    btnSave.addEventListener('click', async () => {
      const player_id = inputPlayer.value;
      const timeslot = inputTimeslot.value;
      const notesEl = document.getElementById('ps-notes');
      const slotSel = document.getElementById('ps-slot');
      const targetSel = document.getElementById('ps-target');
      const targetTeam = document.getElementById('ps-target-team');
      const notes = notesEl ? notesEl.value : '';
      const slot_code = slotSel ? slotSel.value : '';
      const target_type = targetSel ? targetSel.value : '';
      const target_team_name = targetTeam ? targetTeam.value : '';
      if (!player_id || !timeslot || !slot_code || !target_type){
        if (errBox){ errBox.textContent = 'Please choose Slot and Target.'; errBox.classList.remove('d-none'); }
        return;
      }

      // UI: prevent double submit
      btnSave.disabled = true;
      if (errBox){ errBox.classList.add('d-none'); errBox.textContent = ''; }

      try {
        const csrfToken = getCsrf();
        const resp = await fetch(actionUrl, {
          method: 'POST',
          headers: {
            'Accept': 'application/json',
            'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8',
            'X-CSRFToken': getCsrf(),
            'X-Requested-With': 'XMLHttpRequest'
          },
          body: new URLSearchParams({
            csrfmiddlewaretoken: csrfToken,
            player_id: player_id,
            player: player_id,
            timeslot: timeslot,
            slot_code: slot_code,
            target_type: target_type,
            target_team_name: target_team_name,
            notes: notes
          }).toString()
        });

        // Handle response
        if (resp.redirected) {
          // Auth middleware may redirect to login; follow it in-page
          window.location.href = resp.url;
          return;
        }

        // Treat any 2xx as success, regardless of content-type
        if (resp.status < 200 || resp.status >= 300) {
          let msg = `Failed (${resp.status})`;
          try {
            const t = await resp.text();
            if (t && t.length < 500) msg = t;
          } catch (_) {}
          throw new Error(msg);
        }

        // Success: flip the cell to planned badge
        const row = document.querySelector(`tr[data-pid="${player_id}"]`);
        if (row){
          const cell = row.querySelector(`button.plan-sub-link[data-timeslot="${timeslot}"]`)?.closest('td');
          if (cell){
            cell.innerHTML = '<span class="badge bg-primary-subtle text-primary" title="Sub already planned">sub ✓</span>';
          }
        }
        const closeBtn = modalEl.querySelector('[data-bs-dismiss="modal"]');
        if (closeBtn) closeBtn.click();
      } catch (err) {
        console.error('SubPlan save failed', err);
        if (errBox){
          errBox.textContent = err.message || 'Unable to save sub plan';
          errBox.classList.remove('d-none');
        }
      } finally {
        btnSave.disabled = false;
      }
    });
  }
})();
(function(){
    const sel = document.getElementById('season-select');
    if (sel && !sel.disabled) sel.addEventListener('change', function(){ sel.form && sel.form.submit(); });
  })();

// Resolve endpoints from DOM (CSP-safe)
var scheduleCfg = document.getElementById('schedule-config');
var availabilityUrl = scheduleCfg ? scheduleCfg.getAttribute('data-availability-url') : null;
var subAvailabilityUrl = scheduleCfg ? scheduleCfg.getAttribute('data-sub-availability-url') : null;

// Helper to get CSRF token from cookie
function getCookie(name) {
  var cookieValue = null;
  if (document.cookie && document.cookie !== '') {
    var cookies = document.cookie.split(';');
    for (var i = 0; i < cookies.length; i++) {
      var cookie = cookies[i].trim();
      if (cookie.substring(0, name.length + 1) === (name + '=')) {
        cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
        break;
      }
    }
  }
  return cookieValue;
}
var csrftoken = getCookie('csrftoken');

      document.addEventListener('click', async function(e) {
      const btn = e.target.closest('.avail-btn');
      if (!btn) return;
      const fixtureId = btn.getAttribute('data-fixture');
      const status = btn.getAttribute('data-status'); // 'A' or 'N'

      // Optimistically update UI; we'll also reconcile after server response
      const group = btn.closest('.btn-group');
      const yay = group.querySelector('[data-status="A"]');
      const nay = group.querySelector('[data-status="N"]');
      if (status === 'A') {
      yay.classList.remove('btn-outline-secondary'); yay.classList.add('btn-success');
      nay.classList.remove('btn-danger'); nay.classList.add('btn-outline-secondary');
  } else {
      nay.classList.remove('btn-outline-secondary'); nay.classList.add('btn-danger');
      yay.classList.remove('btn-success'); yay.classList.add('btn-outline-secondary');
  }

      try {
      if (!availabilityUrl) {
        throw new Error('Missing availability endpoint');
      }
      const resp = await fetch(availabilityUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrftoken },
      body: JSON.stringify({ fixture_id: fixtureId, status: status })
  });
      if (!resp.ok) {
      // revert UI if failed
      yay.classList.remove('btn-success'); yay.classList.add('btn-outline-secondary');
      nay.classList.remove('btn-danger'); nay.classList.add('btn-outline-secondary');
      alert('Could not update availability. Please try again.');
  }
  } catch (err) {
      // revert UI if failed
      const yay = group.querySelector('[data-status="A"]');
      const nay = group.querySelector('[data-status="N"]');
      yay.classList.remove('btn-success'); yay.classList.add('btn-outline-secondary');
      nay.classList.remove('btn-danger'); nay.classList.add('btn-outline-secondary');
      alert('Network error while updating availability.');
  }
  });

        // Click handler for sub availability buttons
  document.addEventListener('click', async function(e) {
    const btn = e.target.closest('.subavail-btn');
    if (!btn) return;
    const fixtureId = btn.getAttribute('data-fixture');
    const timeslot = btn.getAttribute('data-timeslot');
    const currentlyOn = btn.getAttribute('data-active') === '1';
    const turnOn = !currentlyOn;

    // Optimistic UI toggle
    const setOn = (el, on) => {
      el.setAttribute('data-active', on ? '1' : '0');
      el.classList.toggle('btn-primary', on);
      el.classList.toggle('btn-outline-secondary', !on);
    };
    setOn(btn, turnOn);

    try {
      if (!subAvailabilityUrl) {
        throw new Error('Missing sub-availability endpoint');
      }
      const resp = await fetch(subAvailabilityUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrftoken },
        body: JSON.stringify({ fixture_id: fixtureId, timeslot: timeslot, on: turnOn })
      });
      if (!resp.ok) {
        // Revert on error
        setOn(btn, currentlyOn);
        const text = await resp.text();
        alert(text || 'Could not update sub availability.');
      }
    } catch (err) {
      // Revert on network error
      setOn(btn, currentlyOn);
      alert('Network error while updating sub availability.');
    }
  });

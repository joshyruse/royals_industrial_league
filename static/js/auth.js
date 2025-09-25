

// Password visibility toggles for accept-invite & auth forms

function togglePasswords() {
  const pw1 = document.getElementById('id_new_password1');
  const pw2 = document.getElementById('id_new_password2');
  if (!pw1 || !pw2) return;
  const type = pw1.type === 'password' ? 'text' : 'password';
  pw1.type = type;
  pw2.type = type;
}

document.addEventListener('DOMContentLoaded', function () {
  // Checkbox support (legacy, if present)
  const cb = document.getElementById('show-password-checkbox');
  if (cb) cb.addEventListener('change', togglePasswords);

  // Eye icon buttons within input-group (event delegation)
  document.addEventListener('click', function (e) {
    const btn = e.target.closest('.toggle-password');
    if (!btn) return;
    e.preventDefault();

    // Preferred: explicit target by ID
    let input = null;
    const targetId = btn.getAttribute('data-target');
    if (targetId) {
      input = document.getElementById(targetId);
    }

    // Fallback: find input within the same input-group
    if (!input) {
      const group = btn.closest('.input-group');
      if (group) {
        input = group.querySelector('input[type="password"], input[type="text"]');
      }
    }

    if (!input) return;

    // Toggle visibility
    input.type = (input.type === 'password') ? 'text' : 'password';

    // Swap icon classes if present
    const icon = btn.querySelector('i');
    if (icon) {
      icon.classList.toggle('bi-eye');
      icon.classList.toggle('bi-eye-slash');
    }

    // Accessibility state
    const pressed = btn.getAttribute('aria-pressed') === 'true';
    btn.setAttribute('aria-pressed', pressed ? 'false' : 'true');
  });
});
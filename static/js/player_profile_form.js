(function(){
    const STORAGE_KEY = 'profileOpenSections';

    function readOpenSet(){
      try {
        const raw = localStorage.getItem(STORAGE_KEY);
        if(!raw) return new Set();
        const arr = JSON.parse(raw);
        return new Set(Array.isArray(arr) ? arr : []);
      } catch(e){ return new Set(); }
    }

    function writeOpenSet(set){
      try { localStorage.setItem(STORAGE_KEY, JSON.stringify(Array.from(set))); } catch(e) {}
    }

    function bindCollapse(collapseId, iconId){
      const el = document.getElementById(collapseId);
      const icon = document.getElementById(iconId);
      if(!el) return;
      const openSet = readOpenSet();

      el.addEventListener('shown.bs.collapse', function(){
        if(icon){ icon.classList.replace('bi-chevron-right','bi-chevron-down'); }
        const s = readOpenSet();
        s.add(collapseId);
        writeOpenSet(s);
      });
      el.addEventListener('hidden.bs.collapse', function(){
        if(icon){ icon.classList.replace('bi-chevron-down','bi-chevron-right'); }
        const s = readOpenSet();
        s.delete(collapseId);
        writeOpenSet(s);
      });
    }

    function restoreAllWhenReady(tries){
      tries = (typeof tries === 'number') ? tries : 12;
      const bs = window.bootstrap;
      const openSet = readOpenSet();
      if(!openSet.size) return;

      const ok = bs && bs.Collapse;
      if(ok){
        openSet.forEach(function(id){
          const target = document.getElementById(id);
          if(target && target.classList.contains('collapse')){
            try {
              const c = new bs.Collapse(target, { toggle: false });
              c.show();
            } catch(e) { /* ignore per item */ }
          }
        });
        return;
      }
      if(tries > 0){ setTimeout(function(){ restoreAllWhenReady(tries-1); }, 100); }
    }

    document.addEventListener('DOMContentLoaded', function(){
      bindCollapse('profileSection','icon-profile');
      bindCollapse('notifSection','icon-notif');
      bindCollapse('securitySection','icon-security');
      restoreAllWhenReady();

      // Password visibility toggles (supports data-target-id or nearest input in the same .input-group)
      var toggles = document.querySelectorAll('.toggle-pass');
      Array.prototype.forEach.call(toggles, function(btn){
        btn.addEventListener('click', function(){
          var targetId = btn.getAttribute('data-target-id');
          var input = targetId ? document.getElementById(targetId) : null;

          // Fallback: try the closest input inside the same input-group
          if(!input){
            var group = btn.closest ? btn.closest('.input-group') : null;
            if(group){ input = group.querySelector('input'); }
          }
          if(!input) return;

          var isHidden = (input.getAttribute('type') === 'password');
          input.setAttribute('type', isHidden ? 'text' : 'password');

          var icon = btn.querySelector('i');
          if(icon){
            // Ensure a deterministic state: keep either bi-eye (show) or bi-eye-slash (hide)
            icon.classList.remove(isHidden ? 'bi-eye' : 'bi-eye-slash');
            icon.classList.add(isHidden ? 'bi-eye-slash' : 'bi-eye');
          }
          btn.setAttribute('aria-label', isHidden ? 'Hide password' : 'Show password');
        });
      });
        // Cancel buttons should clear section from localStorage
  document.addEventListener('click', function (e) {
    const a = e.target.closest('a.cancel-section');
    if (!a) return;
    const id = a.getAttribute('data-section');
    if (id) {
      const s = readOpenSet();
      s.delete(id);
      writeOpenSet(s);
    }
    // allow navigation to proceed
  }, { passive: true });

      // --- SMS Verification modal wiring ---
      var modalEl = document.getElementById('smsVerifyModal');
      var displayPhone = document.getElementById('display-sms-phone');
      var openVerifyBtn = document.getElementById('openVerifyBtn');
      var badge = document.getElementById('phone-verify-status');
      var formEl = document.getElementById('sms-verify-form');
      var phoneInputModal = document.getElementById('sms-phone');
      // Ensure no HTML maxlength blocks formatted text; we enforce 10 digits via JS
      if (phoneInputModal) { phoneInputModal.removeAttribute('maxlength'); }
      var codeInput = document.getElementById('sms-code');
      var sendBtn = document.getElementById('send-otp-btn');
      var verifyBtn = document.getElementById('verify-otp-btn');
      var consentChk = document.getElementById('sms-consent');
      var consentBtn = document.getElementById('sms-consent-btn');
      if (consentBtn) {
        consentBtn.disabled = true;
        consentBtn.setAttribute('aria-disabled', 'true');
      }
      var sentMsg = document.getElementById('otp-sent-msg');
      var isSendingOtp = false;
      var isVerifyingOtp = false;

      function getCsrfToken(){
        // Prefer the token inside the modal form; fallback to a page-level input
        var field = formEl ? formEl.querySelector('input[name="csrfmiddlewaretoken"]') : null;
        if(field && field.value) return field.value;
        var globalField = document.querySelector('input[name="csrfmiddlewaretoken"]');
        return globalField ? globalField.value : '';
      }

      function setBadgeVerified(){
        if(!badge) return;
        badge.textContent = 'Verified';
        badge.classList.remove('bg-secondary');
        badge.classList.add('bg-success');
      }
      function setBadgeUnverified(){
        if(!badge) return;
        badge.textContent = 'Not verified';
        badge.classList.remove('bg-success');
        badge.classList.add('bg-secondary');
      }
      function onlyDigits(str){
        return (str || '').replace(/\D+/g, '');
      }
      function formatUsPhone(digits){
        var d = onlyDigits(digits).slice(0, 10);
        if(d.length < 4) return d;
        if(d.length < 7) return '(' + d.slice(0,3) + ') ' + d.slice(3);
        return '(' + d.slice(0,3) + ') ' + d.slice(3,6) + '-' + d.slice(6);
      }
      function formatAndPreserveCaret(inputEl){
        if(!inputEl) return;
        var start = inputEl.selectionStart || 0;
        var raw = inputEl.value || '';
        // Count how many digits were before the caret
        var digitsBefore = onlyDigits(raw.slice(0, start)).length;
        // Recompute digits (max 10) and formatted string
        var digits = onlyDigits(raw).slice(0,10);
        var pretty = formatUsPhone(digits);
        inputEl.value = pretty;
        // Move caret to position after the same number of digits
        var pos = 0, seen = 0;
        while (pos < pretty.length && seen < digitsBefore){
          if (/\d/.test(pretty.charAt(pos))) { seen++; }
          pos++;
        }
        // If user typed at end, keep caret at end
        if (digitsBefore >= digits.length) { pos = pretty.length; }
        try { inputEl.setSelectionRange(pos, pos); } catch(e) {}
      }

      // When modal opens, prefill phone from main field
      if(modalEl){
        modalEl.addEventListener('show.bs.modal', function(){
          if(phoneInputModal){
            var existingDigits = displayPhone ? onlyDigits(displayPhone.value) : '';
            phoneInputModal.value = existingDigits ? formatUsPhone(existingDigits) : '';
            try { var L = phoneInputModal.value.length; phoneInputModal.setSelectionRange(L, L); } catch(e) {}
          }
          if(codeInput){ codeInput.value = ''; }
          if(sentMsg){ sentMsg.classList.add('d-none'); }
          // Gate the single button behind consent
          if (verifyBtn) {
            var allow = !!(consentChk && consentChk.checked);
            verifyBtn.disabled = !allow;
            if (!allow) verifyBtn.setAttribute('aria-disabled', 'true');
            else verifyBtn.removeAttribute('aria-disabled');
          }

          // Keep button state in sync when user toggles consent
          if (consentChk && verifyBtn) {
            consentChk.addEventListener('change', function(){
              var allow2 = !!consentChk.checked;
              verifyBtn.disabled = !allow2;
              if (!allow2) verifyBtn.setAttribute('aria-disabled', 'true');
              else verifyBtn.removeAttribute('aria-disabled');
            }, { once: true });
          }
        });
      }
      if(phoneInputModal){
        phoneInputModal.addEventListener('input', function(){
          formatAndPreserveCaret(phoneInputModal);
        });
      }


      // Helper: POST form-encoded
      function postForm(url, data){
        var body = new URLSearchParams(data);
        return fetch(url, {
          method: 'POST',
          headers: {
            'X-CSRFToken': getCsrfToken(),
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8'
          },
          body: body,
          credentials: 'same-origin'
        }).then(function(r){
          if(!r.ok){ return r.json().catch(function(){ return {error: 'Request failed'}; }).then(function(j){ throw j; }); }
          return r.json();
        });
      }

      // Cooldown for resend
      // replace the whole startCooldown(...) and the var above it if present
      var cooldownTimer = null;
      function startCooldown(seconds){
        if(!sendBtn) return;
        var rem = seconds;
        sendBtn.disabled = true;
        sendBtn.setAttribute('aria-disabled', 'true');
        var original = sendBtn.getAttribute('data-original-text') || sendBtn.textContent;
        sendBtn.setAttribute('data-original-text', original);
        sendBtn.textContent = 'Resend in ' + rem + 's';
        if (cooldownTimer) clearInterval(cooldownTimer);
        cooldownTimer = setInterval(function(){
          rem -= 1;
          if(rem <= 0){
            clearInterval(cooldownTimer);
            cooldownTimer = null;
            sendBtn.disabled = false;
            sendBtn.removeAttribute('aria-disabled');
            sendBtn.textContent = original;
          } else {
            sendBtn.textContent = 'Resend in ' + rem + 's';
          }
        }, 1000);
      }

      // replace the whole if(sendBtn){ ... } block
      if(sendBtn){
        sendBtn.addEventListener('click', function(){
          if (sendBtn.disabled || isSendingOtp) return;
          var phone = onlyDigits((phoneInputModal && phoneInputModal.value || '').trim());
          if(!phone){ return; }

          isSendingOtp = true;
          sendBtn.disabled = true;
          sendBtn.setAttribute('aria-disabled', 'true');

          postForm('/api/sms/start/', { phone: phone })
            .then(function(){
              if(sentMsg){
                sentMsg.classList.remove('d-none','text-danger');
                sentMsg.classList.add('text-success');
                sentMsg.textContent = 'Code sent! Check your phone.';
              }
              startCooldown(30);
            })
            .catch(function(err){
              sendBtn.disabled = false;
              sendBtn.removeAttribute('aria-disabled');
              if(sentMsg){
                sentMsg.classList.remove('text-success');
                sentMsg.classList.remove('d-none');
                sentMsg.classList.add('text-danger');
                sentMsg.textContent = (err && err.error) || 'Failed to send code';
              }
            })
            .finally(function(){ isSendingOtp = false; });
        });
      }

      // Verify + Consent: single button flow
      if(verifyBtn){
        verifyBtn.addEventListener('click', function(e){
          if (isVerifyingOtp) return;
          if (e) { e.preventDefault(); e.stopPropagation(); }
          // Must have consent checked to proceed
          if (!consentChk || !consentChk.checked) { return; }
          var phone = onlyDigits((phoneInputModal && phoneInputModal.value || '').trim());
          var code  = (codeInput && codeInput.value || '').trim();
          if(!phone || !code){ return; }
          verifyBtn.disabled = true;
          verifyBtn.setAttribute('aria-disabled','true');
          isVerifyingOtp = true;

          // Step 1: Verify the code
          postForm('/api/sms/verify/', { phone: phone, code: code })
            // Step 2: On success, immediately persist consent
            .then(function(){
              var consentLabel = document.querySelector('label[for="sms-consent"]');
              var consentText = consentLabel ? consentLabel.textContent.trim() : 'I agree to receive SMS updates.';
              return postForm('/api/sms/consent/', { consent: 'true', consent_text: consentText });
            })
            // Step 3: Finalize UI only after both calls succeed
            .then(function(){
              setBadgeVerified();
              var smsToggle = document.getElementById('id_sms_enabled') || document.querySelector('[name="sms_enabled"]');
              if (smsToggle) { smsToggle.disabled = false; }
              var hint = document.getElementById('sms-enable-hint');
              if (hint) { hint.classList.remove('d-none'); }
              var pre = document.getElementById('sms-preverify-hint');
              if (pre) { pre.classList.add('d-none'); }
              if(displayPhone && phoneInputModal){
                displayPhone.value = formatUsPhone(onlyDigits(phoneInputModal.value));
              }
              if(openVerifyBtn){ openVerifyBtn.textContent = 'Re-Verify'; }
              try {
                var modal = bootstrap && bootstrap.Modal ? bootstrap.Modal.getOrCreateInstance(modalEl) : null;
                if(modal){ modal.hide(); }
              } catch(e) {}
            })
            .catch(function(err){
              console.warn('OTP verify+consent error', err);
              var msg = (err && err.error) ? err.error : 'Verification failed';
              if(codeInput){ codeInput.classList.add('is-invalid'); }
              var help = document.createElement('div');
              help.className = 'invalid-feedback d-block';
              help.textContent = msg;
              if(codeInput && codeInput.parentNode){ codeInput.parentNode.appendChild(help); }
            })
            .finally(function(){
              verifyBtn.disabled = false;
              verifyBtn.removeAttribute('aria-disabled');
              isVerifyingOtp = false;
            });
        });
      }

      // Fallback delegation to catch clicks even if direct listeners failed
      document.addEventListener('click', function(e){
        var t = e.target;
        if(!t) return;

        if(t.id === 'send-otp-btn'){
          if (t.disabled || t.getAttribute('aria-disabled') === 'true' || isSendingOtp) return;

          e.preventDefault();
          var phoneField = document.getElementById('sms-phone');
          var phone = onlyDigits((phoneField && phoneField.value || '').trim());
          if(!phone) return;

          // lock button + set in-flight
          isSendingOtp = true;
          t.disabled = true;
          t.setAttribute('aria-disabled', 'true');

          postForm('/api/sms/start/', { phone: phone })
            .then(function(){
              var sent = document.getElementById('otp-sent-msg');
              if(sent){
                sent.classList.remove('d-none');
                sent.classList.remove('text-danger');
                sent.classList.add('text-success');
                sent.textContent = 'Code sent! Check your phone.';
              }
              startCooldown(30);
            })
            .catch(function(err){
              var sent = document.getElementById('otp-sent-msg');
              if(sent){
                sent.classList.remove('d-none');
                sent.classList.remove('text-success');
                sent.classList.add('text-danger');
                sent.textContent = (err && err.error) || 'Failed to send code';
              }
            })
            .finally(function(){ if (cooldownTimer === null) { t.disabled = false; t.removeAttribute('aria-disabled'); } });
        }

        if(t.id === 'verify-otp-btn'){
          if (isVerifyingOtp) return;
          e.preventDefault();
          var consent = document.getElementById('sms-consent');
          if (!consent || !consent.checked) return;
          var phoneField2 = document.getElementById('sms-phone');
          var codeField   = document.getElementById('sms-code');
          var phone2 = onlyDigits((phoneField2 && phoneField2.value || '').trim());
          var code   = (codeField && codeField.value || '').trim();
          if(!phone2 || !code) return;
          t.disabled = true; t.setAttribute('aria-disabled','true');
          isVerifyingOtp = true;

          postForm('/api/sms/verify/', { phone: phone2, code: code })
            .then(function(){
              var label = document.querySelector('label[for="sms-consent"]');
              var text  = label ? label.textContent.trim() : 'I agree to receive SMS updates.';
              return postForm('/api/sms/consent/', { consent: 'true', consent_text: text });
            })
            .then(function(){
              setBadgeVerified();
              var smsToggle = document.getElementById('id_sms_enabled') || document.querySelector('[name="sms_enabled"]');
              if (smsToggle) { smsToggle.disabled = false; }
              var hint = document.getElementById('sms-enable-hint');
              if (hint) { hint.classList.remove('d-none'); }
              var pre = document.getElementById('sms-preverify-hint');
              if (pre) { pre.classList.add('d-none'); }
              if(displayPhone && phoneInputModal){
                displayPhone.value = formatUsPhone(onlyDigits(phoneInputModal.value));
              }
              if(openVerifyBtn){ openVerifyBtn.textContent = 'Re-Verify'; }
              try {
                var modal2 = bootstrap && bootstrap.Modal ? bootstrap.Modal.getOrCreateInstance(document.getElementById('smsVerifyModal')) : null;
                if(modal2){ modal2.hide(); }
              } catch(e) {}
            })
            .catch(function(err){
              var codeField2 = document.getElementById('sms-code');
              if(codeField2){ codeField2.classList.add('is-invalid'); }
              var help = document.createElement('div');
              help.className = 'invalid-feedback d-block';
              help.textContent = (err && err.error) ? err.error : 'Verification failed';
              if(codeField2 && codeField2.parentNode){ codeField2.parentNode.appendChild(help); }
            })
            .finally(function(){
              t.disabled = false; t.removeAttribute('aria-disabled');
              isVerifyingOtp = false;
            });
        }
      });
    });
})();
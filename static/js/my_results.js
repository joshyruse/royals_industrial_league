  (function(){
    var sel = document.getElementById('season-select');
    if (sel && !sel.disabled) sel.addEventListener('change', function(){ sel.form && sel.form.submit(); });
  })();
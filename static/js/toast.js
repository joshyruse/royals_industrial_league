document.addEventListener('DOMContentLoaded', function(){
  var container = document.getElementById('toast-stack');
  if (!container) return;
  var toasts = container.querySelectorAll('.toast');
  toasts.forEach(function(el){
    try {
      var t = bootstrap.Toast.getOrCreateInstance(el, { delay: 3500, autohide: true });
      t.show();
    } catch(e) {}
  });
});
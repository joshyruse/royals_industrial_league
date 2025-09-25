// Make any table row with .row-link[data-href] clickable
document.addEventListener('click', function(e){
  var tr = e.target.closest && e.target.closest('tr.row-link[data-href]');
  if (!tr) return;
  var interactive = e.target.closest('a, button, input, label, select, textarea');
  if (interactive) return;
  var url = tr.getAttribute('data-href');
  if (url) window.location = url;
});

document.addEventListener('keydown', function(e){
  if (e.key !== 'Enter' && e.key !== ' ') return;
  var el = document.activeElement;
  if (!el || !el.closest) return;
  var tr = el.closest('tr.row-link[data-href]');
  if (!tr) return;
  e.preventDefault();
  var url = tr.getAttribute('data-href');
  if (url) window.location = url;
});
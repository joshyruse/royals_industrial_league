(function(){
  const toggler = document.querySelector('.navbar-toggler');
  const panel = document.getElementById('mobileNav');
  if (!toggler || !panel) return;

  const getOffcanvas = () => {
    try { return bootstrap.Offcanvas.getOrCreateInstance(panel); } catch(e) { return null; }
  };

  const isMobile = () => window.matchMedia('(max-width: 991.98px)').matches;

  function lockBody(lock){ document.body.classList.toggle('nav-open', !!lock); }
  function closeAllSubmenus(){
    panel.querySelectorAll('.dropdown-menu.show').forEach(m => {
      m.classList.remove('show');
      const toggle = m.previousElementSibling;
      if (toggle && toggle.matches('[data-bs-toggle="dropdown"]')) {
        toggle.setAttribute('aria-expanded', 'false');
      }
    });
  }

  // Offcanvas lifecycle
  panel.addEventListener('shown.bs.offcanvas', function(){ if (isMobile()) lockBody(true); });
  panel.addEventListener('hide.bs.offcanvas', function(){ lockBody(false); closeAllSubmenus(); });

  // --- Toggle dropdowns inside the offcanvas (mobile) ---
  function handleToggle(ev){
    const toggle = ev.target.closest('[data-bs-toggle="dropdown"]');
    if (!toggle || !panel.contains(toggle)) return;
    if (!isMobile()) return; // desktop uses regular navbar, not offcanvas

    ev.preventDefault();
    ev.stopPropagation();
    if (ev.stopImmediatePropagation) ev.stopImmediatePropagation();

    const menu = toggle.nextElementSibling;
    if (!menu || !menu.classList.contains('dropdown-menu')) return;

    const willOpen = !menu.classList.contains('show');
    // Close other menus for cleanliness
    panel.querySelectorAll('.dropdown-menu.show').forEach(m => {
      if (m !== menu) {
        m.classList.remove('show');
        const t = m.previousElementSibling;
        if (t && t.matches('[data-bs-toggle="dropdown"]')) t.setAttribute('aria-expanded', 'false');
        const p = m.closest('.dropdown');
        if (p) p.classList.remove('show');
      }
    });

    menu.classList.toggle('show', willOpen);
    toggle.setAttribute('aria-expanded', willOpen ? 'true' : 'false');
    const parent = toggle.closest('.dropdown');
    if (parent) parent.classList.toggle('show', willOpen);
  }

  panel.addEventListener('click', handleToggle, true); // capture phase to preempt Bootstrap
  panel.addEventListener('touchstart', function(ev){
    // Early toggle on touch to avoid delayed click on iOS
    const toggle = ev.target.closest('[data-bs-toggle="dropdown"]');
    if (!toggle || !panel.contains(toggle)) return;
    if (!isMobile()) return;
    ev.preventDefault();
    ev.stopPropagation();
    if (ev.stopImmediatePropagation) ev.stopImmediatePropagation();
    handleToggle(ev);
  }, { passive: false, capture: true });
  panel.addEventListener('keydown', function(ev){ if (ev.key === 'Enter' || ev.key === ' ') handleToggle(ev); });

  // --- Close offcanvas on real navigation clicks (not dropdown toggles) ---
  panel.addEventListener('click', function(ev){
    if (!isMobile()) return;
    const link = ev.target.closest('a');
    if (!link || !panel.contains(link)) return;

    // Never treat the dropdown toggle as a navigation click
    if (link.matches('[data-bs-toggle="dropdown"]')) return;

    const isDropdownItem = link.matches('.dropdown-item');
    const isNavLink = link.matches('.nav-link');

    if (isDropdownItem || isNavLink) {
      const inst = getOffcanvas();
      if (inst) inst.hide();
    }
  });

  // Outside click / ESC still closes offcanvas
  document.addEventListener('click', function(ev){
    if (!isMobile()) return;
    const inst = getOffcanvas();
    const open = panel.classList.contains('show');
    if (!open) return;
    const inside = panel.contains(ev.target) || toggler.contains(ev.target);
    if (!inside) { inst && inst.hide(); }
  });
  document.addEventListener('keydown', function(ev){ if (ev.key === 'Escape') { const inst = getOffcanvas(); inst && inst.hide(); }});

  // Clean up on resize
  let t = null;
  window.addEventListener('resize', function(){
    clearTimeout(t);
    t = setTimeout(() => { if (!isMobile()) { lockBody(false); closeAllSubmenus(); } }, 120);
  });
})();
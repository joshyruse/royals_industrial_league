(function(){
    // Map result code -> [homePoints, awayPoints]
    var MAP = { 'W': [2,0], 'WF': [2,0], 'T': [1,1], 'L': [0,2], 'LF': [0,2] };
    function recalc(){
      var home = 0, away = 0;
      var selects = document.querySelectorAll('select[name^="score-"][name$="-result"]');
      selects.forEach(function(sel){
        var val = sel.value;
        if (MAP[val]) { home += MAP[val][0]; away += MAP[val][1]; }
      });
      var th = document.getElementById('total-home');
      var ta = document.getElementById('total-away');
      if (th) th.textContent = home;
      if (ta) ta.textContent = away;
    }
    document.addEventListener('change', function(e){
      if (e.target && e.target.matches('select[name^="score-"][name$="-result"]')) recalc();
    });
    // Initial calc on load
    recalc();
  })();
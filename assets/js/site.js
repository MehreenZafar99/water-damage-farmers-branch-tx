(function () {
  var toggle = document.querySelector('.menu-toggle');
  var nav = document.getElementById('site-nav');
  if (toggle && nav) {
    toggle.addEventListener('click', function () {
      var open = nav.classList.toggle('open');
      toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
      toggle.textContent = open ? 'Close' : 'Menu';
    });
  }

  function wireChecklist(panel) {
    var boxes = panel.querySelectorAll('input[type="checkbox"]');
    var bar = panel.querySelector('.progress span') || panel.querySelector('#bar');
    var label = panel.querySelector('.progress-label') || panel.querySelector('#progress-label');
    if (!boxes.length || !bar || !label) return;
    function update() {
      var done = 0;
      boxes.forEach(function (b) { if (b.checked) done++; });
      bar.style.width = (done / boxes.length * 100) + '%';
      label.textContent = done + ' of ' + boxes.length + ' done';
      panel.classList.toggle('all-done', done === boxes.length);
    }
    boxes.forEach(function (b) { b.addEventListener('change', update); });
  }

  var first10 = document.getElementById('first10');
  if (first10) wireChecklist(first10);
  document.querySelectorAll('.checklist-panel').forEach(function (panel) {
    if (panel.id === 'first10') return;
    wireChecklist(panel);
  });

  var year = document.getElementById('year');
  if (year) year.textContent = new Date().getFullYear();
})();

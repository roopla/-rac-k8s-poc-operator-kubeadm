(function () {
  // Copy buttons: copy the commands without the "where" label
  document.querySelectorAll('.cmd').forEach(function (box) {
    var btn = box.querySelector('.copy'), code = box.querySelector('pre code');
    if (!btn || !code) return;
    btn.addEventListener('click', function () {
      var text = code.innerText.replace(/\n$/, '');
      var done = function () { btn.textContent = 'Copied'; btn.classList.add('done'); setTimeout(function () { btn.textContent = 'Copy'; btn.classList.remove('done'); }, 1600); };
      var fallback = function () {
        var r = document.createRange(); r.selectNodeContents(code);
        var s = window.getSelection(); s.removeAllRanges(); s.addRange(r);
        btn.textContent = 'Selected: press Ctrl+C';
      };
      try {
        if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text).then(done, fallback);
        else fallback();
      } catch (e) { fallback(); }
    });
  });
  // Highlight the current section in the contents
  var links = Array.prototype.slice.call(document.querySelectorAll('.toc a'));
  var map = {};
  links.forEach(function (a) { map[a.getAttribute('href').slice(1)] = a; });
  if ('IntersectionObserver' in window) {
    var obs = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) {
          links.forEach(function (a) { a.classList.remove('active'); });
          var a = map[e.target.id]; if (a) a.classList.add('active');
        }
      });
    }, { rootMargin: '0px 0px -75% 0px' });
    document.querySelectorAll('.sec h2[id]').forEach(function (h) { obs.observe(h); });
  }
  // Collapse the contents by default on narrow screens
  if (window.matchMedia && window.matchMedia('(max-width: 960px)').matches) {
    var d = document.querySelector('.toc details'); if (d) d.removeAttribute('open');
  }
})();
(function () {
  document.querySelectorAll('.copy-mini').forEach(function (b) {
    b.addEventListener('click', function () {
      var t = b.getAttribute('data-copy');
      var ok = function () { b.textContent = 'Copied'; b.classList.add('done'); setTimeout(function () { b.textContent = 'Copy'; b.classList.remove('done'); }, 1600); };
      try { if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(t).then(ok, function () { b.textContent = 'Select and copy'; }); else b.textContent = 'Select and copy'; } catch (e) { b.textContent = 'Select and copy'; }
    });
  });
})();

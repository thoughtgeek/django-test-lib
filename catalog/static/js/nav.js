// Minimal hamburger toggle for the sidebar (mobile) (Bootstrap's JS bundle is not loaded).
document.addEventListener('DOMContentLoaded', function () {
  var toggle = document.querySelector('[data-nav-toggle]');
  if (!toggle) { return; }
  var menu = document.getElementById(toggle.getAttribute('aria-controls'));
  toggle.addEventListener('click', function () {
    var open = menu.classList.toggle('show');
    toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && menu.classList.contains('show')) {
      menu.classList.remove('show');
      toggle.setAttribute('aria-expanded', 'false');
      toggle.focus();
    }
  });
});

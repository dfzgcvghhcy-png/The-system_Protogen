(() => {
  const audio = document.getElementById('accessDeniedSound');
  const playDenied = () => {
    if (!audio) return;
    try { audio.currentTime = 0; audio.play().catch(() => {}); } catch (_) {}
  };
  window.playAccessDenied = playDenied;

  window.showAccessDenied = () => {
    playDenied();
    let toast = document.getElementById('accessDeniedToast');
    if (!toast) {
      toast = document.createElement('div');
      toast.id = 'accessDeniedToast';
      toast.textContent = 'Доступ запрещен';
      toast.style.cssText = 'position:fixed;left:50%;top:24px;transform:translateX(-50%);z-index:99999;padding:11px 17px;border:1px solid rgba(255,70,130,.4);border-radius:11px;background:rgba(17,4,14,.96);color:#ff82a5;font:900 10px/1.2 Arial,sans-serif;letter-spacing:1px;box-shadow:0 0 28px rgba(255,70,130,.16);pointer-events:none;';
      document.body.appendChild(toast);
    }
    clearTimeout(window.__accessDeniedTimer);
    window.__accessDeniedTimer = setTimeout(() => toast.remove(), 1600);
  };

  function initAccessControl() {
    document.querySelectorAll('[data-denied], a[href][data-required-role]').forEach(el => {
      el.addEventListener('click', e => { e.preventDefault(); window.showAccessDenied(); });
    });

    // Read-only settings for the Administrator: every attempt to change a control
    // is stopped immediately, while the server also rejects POST as a second layer.
    const form = document.querySelector('form[data-read-only="1"]');
    if (form) {
      form.querySelectorAll('input, select, button').forEach(el => {
        if (el.type === 'hidden') return;
        el.addEventListener('click', e => { e.preventDefault(); e.stopPropagation(); window.showAccessDenied(); });
        el.addEventListener('change', e => { e.preventDefault(); e.stopPropagation(); window.showAccessDenied(); });
        el.addEventListener('input', e => { e.preventDefault(); e.stopPropagation(); window.showAccessDenied(); });
      });
      form.addEventListener('submit', e => { e.preventDefault(); window.showAccessDenied(); });
    }
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initAccessControl);
  else initAccessControl();
})();

(() => {
  const $ = (s, root = document) => root.querySelector(s);
  const $$ = (s, root = document) => [...root.querySelectorAll(s)];

  // ---------------------------------------------------------
  // CHAT MODAL
  // "ЗАЙТИ В ЧАТ" opens it. Repeated clicks keep it OPEN.
  // Only X, backdrop click, or Escape closes it.
  // ---------------------------------------------------------
  const chatOverlay = $('#chatOverlay');
  const heroChatBtn = $('#heroChatBtn');
  const closeChat = $('#closeChat');
  const input = $('#input');
  const messages = $('#messages');

  function openChat() {
    if (!chatOverlay) return;
    chatOverlay.classList.add('open');
    chatOverlay.setAttribute('aria-hidden', 'false');
    setTimeout(() => input?.focus(), 160);
  }

  function hideChat() {
    if (!chatOverlay) return;
    chatOverlay.classList.remove('open');
    chatOverlay.setAttribute('aria-hidden', 'true');
  }

  heroChatBtn?.addEventListener('click', (e) => {
    e.preventDefault();
    openChat();
  });
  closeChat?.addEventListener('click', hideChat);
  chatOverlay?.addEventListener('click', (e) => {
    if (e.target === chatOverlay) hideChat();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') hideChat();
  });

  function addMessage(text, type = 'bot') {
    if (!messages) return null;
    const div = document.createElement('div');
    div.className = `message ${type === 'user' ? 'user-message' : 'bot-message'}`;
    div.textContent = text;
    messages.appendChild(div);
    messages.scrollTop = messages.scrollHeight;
    return div;
  }

  async function sendMessage() {
    if (!input || !messages) return;
    const text = input.value.trim();
    if (!text) return;

    addMessage(text, 'user');
    input.value = '';

    const thinking = addMessage('Protogen обрабатывает сообщение…', 'bot');
    thinking?.classList.add('thinking');

    try {
      const response = await fetch('/chat', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({message: text})
      });
      const data = await response.json();
      thinking?.remove();
      addMessage(data.response || 'Protogen пока молчит…', 'bot');
    } catch (err) {
      thinking?.remove();
      addMessage('💥 Не удалось связаться с Protogen. Попробуй ещё раз.', 'bot');
      console.error('CHAT:', err);
    }
  }

  $('#sendBtn')?.addEventListener('click', sendMessage);
  input?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });

  // ---------------------------------------------------------
  // USER-ONLY WALLPAPERS
  // Stored locally in this browser. No admin API call.
  // ---------------------------------------------------------
  const WALL_KEY = 'protogen_user_wallpaper_v2';

  const presets = {
    default: {
      image: 'url("/static/bg.png")',
      overlay: 'linear-gradient(180deg,rgba(1,4,9,.58),rgba(1,3,7,.80))',
      size: 'cover'
    },
    violet: {
      image: 'radial-gradient(circle at 72% 20%,rgba(155,69,255,.58),transparent 25%),linear-gradient(135deg,#070317,#17102b 52%,#020609)',
      overlay: 'linear-gradient(180deg,rgba(1,4,8,.28),rgba(1,4,8,.72))',
      size: 'cover'
    },
    nebula: {
      image: 'radial-gradient(circle at 28% 28%,rgba(0,132,255,.58),transparent 22%),radial-gradient(circle at 75% 70%,rgba(155,69,255,.52),transparent 30%),linear-gradient(135deg,#020812,#0a0b20 55%,#020307)',
      overlay: 'linear-gradient(180deg,rgba(1,4,8,.28),rgba(1,4,8,.72))',
      size: 'cover'
    },
    cyber: {
      image: 'linear-gradient(rgba(0,255,225,.11) 1px,transparent 1px),linear-gradient(90deg,rgba(0,255,225,.11) 1px,transparent 1px),linear-gradient(135deg,#02090c,#080616)',
      overlay: 'linear-gradient(180deg,rgba(1,4,8,.26),rgba(1,4,8,.76))',
      size: '22px 22px,22px 22px,auto'
    },
    dark: {
      image: 'linear-gradient(135deg,#010307,#070914 50%,#10051d)',
      overlay: 'linear-gradient(180deg,rgba(1,3,6,.30),rgba(1,3,6,.78))',
      size: 'cover'
    }
  };

  function setWallpaper(id, custom = null, save = true) {
    if (!id) id = 'default';

    if (custom) {
      document.body.style.backgroundImage =
        `linear-gradient(180deg,rgba(1,4,8,.48),rgba(1,3,7,.80)),url("${custom}")`;
      document.body.style.backgroundSize = 'cover';
      document.body.style.backgroundPosition = 'center';
      document.body.style.backgroundAttachment = 'fixed';
    } else {
      const preset = presets[id] || presets.default;
      document.body.style.backgroundImage = `${preset.overlay},${preset.image}`;
      document.body.style.backgroundSize = preset.size;
      document.body.style.backgroundPosition = 'center';
      document.body.style.backgroundAttachment = 'fixed';
    }

    $$('.wall-thumb').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.wall === id);
    });

    if (save) {
      try {
        localStorage.setItem(WALL_KEY, JSON.stringify({id, custom}));
      } catch (err) {
        console.warn('Wallpaper could not be saved locally:', err);
      }
    }
  }

  function loadWallpaper() {
    try {
      const saved = JSON.parse(localStorage.getItem(WALL_KEY) || 'null');
      if (saved?.custom) setWallpaper('custom', saved.custom, false);
      else setWallpaper(saved?.id || 'default', null, false);
    } catch {
      setWallpaper('default', null, false);
    }
  }

  $$('.wall-thumb').forEach(btn => {
    btn.addEventListener('click', () => setWallpaper(btn.dataset.wall));
  });

  $('.wall-main-preview')?.addEventListener('click', () => setWallpaper('default'));

  $('#customWallpaper')?.addEventListener('change', () => {
    const file = $('#customWallpaper').files?.[0];
    if (!file) return;

    if (file.size > 3 * 1024 * 1024) {
      alert('Файл слишком большой. Максимум 3 МБ.');
      $('#customWallpaper').value = '';
      return;
    }

    const reader = new FileReader();
    reader.onload = () => {
      setWallpaper('custom', reader.result);
      $('.wall-main-preview').style.backgroundImage =
        `linear-gradient(180deg,rgba(2,5,9,.15),rgba(2,4,8,.50)),url("${reader.result}")`;
      alert('Готово — эти обои видишь только ты в этом браузере.');
      $('#customWallpaper').value = '';
    };
    reader.readAsDataURL(file);
  });

  loadWallpaper();

  // ---------------------------------------------------------
  // SMALL LIVE VALUES / ANIMATION STATUS
  // ---------------------------------------------------------
  const cpu = $('#cpuValue');
  const ram = $('#ramValue');
  const ping = $('#pingValue');
  const signalState = $('#signalState');

  setInterval(() => {
    if (cpu) cpu.textContent = `${20 + Math.floor(Math.random() * 9)}%`;
    if (ram) ram.textContent = `${38 + Math.floor(Math.random() * 8)}%`;
    if (ping) ping.textContent = `${22 + Math.floor(Math.random() * 13)}ms`;
    if (signalState) {
      const states = ['STABLE', 'SYNC', 'ACTIVE', 'STABLE'];
      signalState.textContent = states[Math.floor(Math.random() * states.length)];
    }
  }, 2200);
})();


// ---------------------------------------------------------
// ADMIN SETTINGS TRANSITION
// Кнопка не открывает панель сразу: сначала короткий
// плавный SYSTEM ACCESS эффект, затем /admin/login.
// ---------------------------------------------------------
(() => {
  const adminLink = document.querySelector('.admin-cta');
  if (!adminLink) return;

  adminLink.addEventListener('click', (event) => {
    const target = adminLink.href;
    if (!target) return;

    event.preventDefault();

    // Защита от двойного клика.
    if (document.body.classList.contains('admin-transitioning')) return;

    document.body.classList.add('admin-transitioning');

    // Даем анимации завершиться, после чего открываем
    // существующую защищенную страницу входа.
    window.setTimeout(() => {
      window.location.href = target;
    }, 720);
  });
})();

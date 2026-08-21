
(() => {
  const $ = (s, root = document) => root.querySelector(s);
  const $$ = (s, root = document) => [...root.querySelectorAll(s)];

  const overlay = $('#settingsOverlay');
  const openSettings = $('#openSettings');
  const closeSettings = $('#closeSettings');
  const wallpaperGrid = $('#wallpaperGrid');
  const customWallpaper = $('#customWallpaper');
  const resetWallpaper = $('#resetWallpaper');
  const chat = $('#chat');
  const input = $('#input');
  const messages = $('#messages');
  const heroChatBtn = $('#heroChatBtn');
  const topChatLink = $('#topChatLink');

  // ---------------------------
  // PUBLIC CHAT
  // ---------------------------
  function openChat() {
    if (!chat) return;
    chat.classList.remove('chat-closed');
    chat.classList.add('chat-open');
    setTimeout(() => input?.focus(), 180);
    chat.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }

  heroChatBtn?.addEventListener('click', (e) => {
    e.preventDefault();
    openChat();
  });

  topChatLink?.addEventListener('click', (e) => {
    e.preventDefault();
    openChat();
  });

  function addMessage(text, type = 'user') {
    const div = document.createElement('div');
    div.className = `message ${type === 'user' ? 'user-message' : 'bot-message'}`;
    div.textContent = text;
    messages?.appendChild(div);
    if (messages) messages.scrollTop = messages.scrollHeight;
    return div;
  }

  async function sendMessage() {
    if (!input || !messages) return;
    const text = input.value.trim();
    if (!text) return;

    addMessage(text, 'user');
    input.value = '';

    const thinking = addMessage('Protogen обрабатывает сообщение…', 'bot');
    thinking.classList.add('thinking');

    try {
      const response = await fetch('/chat', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({message: text})
      });
      const data = await response.json();
      thinking.remove();
      addMessage(data.response || 'Protogen пока молчит…', 'bot');
    } catch (err) {
      thinking.remove();
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

  // ---------------------------
  // USER-ONLY WALLPAPERS
  // localStorage means the choice is stored only in this browser/device.
  // It is not sent to the Flask admin endpoints or PostgreSQL.
  // ---------------------------
  const WALL_KEY = 'protogen_user_wallpaper_v1';

  const presets = {
    default: {
      image: 'url("/static/bg.png")',
      overlay: 'linear-gradient(180deg,rgba(1,5,7,.54),rgba(1,5,7,.78))'
    },
    violet: {
      image: 'radial-gradient(circle at 72% 20%,rgba(155,69,255,.58),transparent 25%),linear-gradient(135deg,#070317,#17102b 52%,#020609)',
      overlay: 'linear-gradient(180deg,rgba(1,4,8,.30),rgba(1,4,8,.70))'
    },
    nebula: {
      image: 'radial-gradient(circle at 28% 28%,rgba(0,132,255,.58),transparent 22%),radial-gradient(circle at 75% 70%,rgba(155,69,255,.52),transparent 30%),linear-gradient(135deg,#020812,#0a0b20 55%,#020307)',
      overlay: 'linear-gradient(180deg,rgba(1,4,8,.30),rgba(1,4,8,.70))'
    },
    cyber: {
      image: 'linear-gradient(rgba(0,255,225,.11) 1px,transparent 1px),linear-gradient(90deg,rgba(0,255,225,.11) 1px,transparent 1px),linear-gradient(135deg,#02090c,#080616)',
      overlay: 'linear-gradient(180deg,rgba(1,4,8,.28),rgba(1,4,8,.76))'
    }
  };

  function setWallpaper(id, custom = null, save = true) {
    if (!id) id = 'default';

    if (custom) {
      document.body.style.backgroundImage =
        `linear-gradient(180deg,rgba(1,5,7,.44),rgba(1,5,7,.76)),url("${custom}")`;
      document.body.style.backgroundSize = 'cover';
      document.body.style.backgroundPosition = 'center';
    } else {
      const preset = presets[id] || presets.default;
      document.body.style.backgroundImage = `${preset.overlay},${preset.image}`;
      document.body.style.backgroundSize = id === 'cyber' ? '20px 20px,20px 20px,auto' : 'cover';
      document.body.style.backgroundPosition = 'center';
      document.body.style.backgroundAttachment = 'fixed';
    }

    $$('.wall-option').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.wall === id);
    });

    if (save) {
      localStorage.setItem(WALL_KEY, JSON.stringify({id, custom}));
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

  $$('.wall-option').forEach(btn => {
    btn.addEventListener('click', () => setWallpaper(btn.dataset.wall));
  });

  customWallpaper?.addEventListener('change', () => {
    const file = customWallpaper.files?.[0];
    if (!file) return;
    if (file.size > 4 * 1024 * 1024) {
      alert('Файл слишком большой. Максимум 4 МБ.');
      customWallpaper.value = '';
      return;
    }

    const reader = new FileReader();
    reader.onload = () => {
      setWallpaper('custom', reader.result);
      alert('Готово — эти обои видишь только ты в этом браузере.');
      customWallpaper.value = '';
    };
    reader.readAsDataURL(file);
  });

  resetWallpaper?.addEventListener('click', () => {
    setWallpaper('default');
  });

  // ---------------------------
  // SETTINGS MODAL
  // ---------------------------
  function showSettings() {
    overlay?.classList.add('open');
    overlay?.setAttribute('aria-hidden', 'false');
  }
  function hideSettings() {
    overlay?.classList.remove('open');
    overlay?.setAttribute('aria-hidden', 'true');
  }

  openSettings?.addEventListener('click', (e) => {
    e.preventDefault();
    showSettings();
  });
  closeSettings?.addEventListener('click', hideSettings);
  overlay?.addEventListener('click', (e) => {
    if (e.target === overlay) hideSettings();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') hideSettings();
  });

  loadWallpaper();
})();

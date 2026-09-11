(() => {
  const root = document.body;
  const box = document.getElementById('assistantCountdown');
  if (!box) return;

  const daysEl = box.querySelector('[data-days]');
  const hoursEl = box.querySelector('[data-hours]');
  const minutesEl = box.querySelector('[data-minutes]');
  const secondsEl = box.querySelector('[data-seconds]');
  const launchRaw = root.dataset.launchAt;
  const launchAt = Date.parse(launchRaw);

  const pad = (n) => String(Math.max(0, n)).padStart(2, '0');
  const updateCountdown = () => {
    if (!Number.isFinite(launchAt)) {
      daysEl.textContent = '--'; hoursEl.textContent = '--'; minutesEl.textContent = '--'; secondsEl.textContent = '--';
      return;
    }
    const diff = launchAt - Date.now();
    if (diff <= 0) {
      daysEl.textContent = '00'; hoursEl.textContent = '00'; minutesEl.textContent = '00'; secondsEl.textContent = '00';
      box.classList.add('is-live');
      return;
    }
    const total = Math.floor(diff / 1000);
    daysEl.textContent = pad(Math.floor(total / 86400));
    hoursEl.textContent = pad(Math.floor((total % 86400) / 3600));
    minutesEl.textContent = pad(Math.floor((total % 3600) / 60));
    secondsEl.textContent = pad(total % 60);
  };
  updateCountdown();
  setInterval(updateCountdown, 1000);

  const notifyBtn = document.getElementById('assistantNotifyBtn');
  const notifyStatus = document.getElementById('assistantNotifyStatus');
  const armedKey = 'protogen_assistant_launch_notify';

  const markArmed = () => {
    localStorage.setItem(armedKey, '1');
    notifyBtn.classList.add('is-armed');
    notifyBtn.textContent = '✓ УВЕДОМЛЕНИЕ ВКЛЮЧЕНО';
    notifyStatus.textContent = 'Браузер напомнит о запуске, если уведомления разрешены.';
  };

  if (localStorage.getItem(armedKey) === '1') markArmed();

  notifyBtn.addEventListener('click', async () => {
    if (!('Notification' in window)) {
      notifyStatus.textContent = 'Этот браузер не поддерживает системные уведомления.';
      markArmed();
      return;
    }
    try {
      const permission = Notification.permission === 'default' ? await Notification.requestPermission() : Notification.permission;
      markArmed();
      if (permission === 'granted') {
        new Notification('Protogen Assistant', { body: 'Уведомления о запуске включены.', icon: '/static/my_avatar.png' });
      } else {
        notifyStatus.textContent = 'Напоминание сохранено, но системные уведомления браузера запрещены.';
      }
    } catch (_) {
      markArmed();
    }
  });
})();

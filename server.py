"""Web panel + Telegram bot in a single process.

    gunicorn server:app --workers 1 --threads 8 --timeout 120

BOT_MODE (env):
    webhook  — Telegram pushes updates to /telegram/webhook (best for Render free:
               an incoming update wakes the sleeping instance by itself);
    polling  — the bot polls Telegram from a background thread (VPS / local);
    off      — web panel only (e.g. the bot runs as a separate worker).
    (empty)  — webhook when a public URL is known (Render sets RENDER_EXTERNAL_URL), else polling.

Only ONE gunicorn worker may be used, otherwise several bots would start.
"""
import asyncio
import hashlib
import hmac
import os
import sys
import threading
import traceback

ROOT = os.path.dirname(os.path.abspath(__file__))
BOT_DIR = os.path.join(ROOT, "bot")

# Hosting logs are pipes: without line buffering print() output appears late or never.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(line_buffering=True)
    except Exception:
        pass

try:  # local runs: read .env (hosting platforms provide real environment variables)
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))
except ImportError:
    pass
if BOT_DIR not in sys.path:
    sys.path.insert(0, BOT_DIR)

from flask import jsonify, request  # noqa: E402

from app import app  # noqa: E402  (the Flask web panel)


def _public_url():
    for key in ("SITE_URL", "PUBLIC_URL", "RENDER_EXTERNAL_URL"):
        value = (os.getenv(key) or "").strip().rstrip("/")
        if value:
            return value if value.startswith("http") else "https://" + value
    return ""


def _bot_mode():
    mode = (os.getenv("BOT_MODE") or "").strip().lower()
    if mode in {"webhook", "polling", "off"}:
        return mode
    if not (os.getenv("BOT_TOKEN") or "").strip():
        return "off"
    return "webhook" if _public_url().startswith("https://") else "polling"


def _webhook_secret():
    explicit = (os.getenv("WEBHOOK_SECRET") or "").strip()
    if explicit:
        return explicit
    # Derived from the token so it is stable across restarts and never public.
    return hashlib.sha256(("protogen-webhook:" + os.getenv("BOT_TOKEN", "")).encode()).hexdigest()[:48]


class BotRunner:
    def __init__(self):
        self.mode = _bot_mode()
        self.loop = None
        self.application = None
        self.ready = threading.Event()
        self.error = None
        self.lock_conn = None
        self.pid = os.getpid()
        self.stage = "created"

    def start(self):
        if self.mode == "off":
            print("🤖 BOT_MODE=off — Telegram-бот в этом процессе не запускается")
            return
        print(f"🤖 Bot thread starting (pid {self.pid}, mode {self.mode})")
        threading.Thread(target=self._thread_main, name="protogen-bot", daemon=True).start()

    def _thread_main(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self._startup())
        except Exception as exc:
            self.error = f"{type(exc).__name__}: {exc}"
            print(f"❌ BOT START ERROR: {self.error}\n{traceback.format_exc()}")
            self.ready.set()
            return
        self.stage = "online"
        self.ready.set()
        self.loop.run_forever()

    async def _startup(self):
        self.stage = "importing bot modules"
        from main import build_application, ALLOWED_UPDATES, post_init, acquire_worker_lock

        if self.mode == "polling":
            self.stage = "waiting for worker lock"
            # Wait at most 60 s for an old instance to stop, then continue anyway.
            self.lock_conn = await asyncio.to_thread(acquire_worker_lock, 60)
        self.stage = "building application"
        application = build_application(with_updater=(self.mode == "polling"))
        self.application = application
        self.stage = "connecting to Telegram (getMe)"
        await application.initialize()
        self.stage = "post_init (jobs, command menus)"
        await post_init(application)  # run_polling()/run_webhook() normally call it; we start manually
        self.stage = "starting application"
        await application.start()
        self.stage = "setting webhook"
        if self.mode == "webhook":
            url = _public_url() + "/telegram/webhook"
            await application.bot.set_webhook(
                url=url, secret_token=_webhook_secret(), allowed_updates=ALLOWED_UPDATES,
                drop_pending_updates=False, max_connections=20,
            )
            print(f"🐾 The system_Protogen запущен (webhook → {url})")
        else:
            await application.bot.delete_webhook(drop_pending_updates=False)
            await application.updater.start_polling(allowed_updates=ALLOWED_UPDATES)
            print("🐾 The system_Protogen запущен (polling в фоне)")

    def feed(self, payload):
        from telegram import Update
        if not self.application or not self.loop:
            return False
        update = Update.de_json(payload, self.application.bot)
        asyncio.run_coroutine_threadsafe(self.application.update_queue.put(update), self.loop)
        return True


_runner = None
_runner_lock = threading.Lock()


def get_runner():
    """Start the bot lazily inside the process that actually serves requests.

    Starting a thread at import time breaks under gunicorn when the app is imported in the
    master and then forked: threads do not survive fork() and locks they held stay locked
    in the child, so the bot in the worker hangs forever in "starting".
    """
    global _runner
    with _runner_lock:
        if _runner is None or _runner.pid != os.getpid():
            _runner = BotRunner()
            _runner.start()
        return _runner


@app.before_request
def _ensure_bot_started():
    get_runner()


@app.route("/telegram/webhook", methods=["POST"])
def telegram_webhook():
    bot_runner = get_runner()
    if bot_runner.mode != "webhook":
        return jsonify({"ok": False, "error": "webhook mode disabled"}), 404
    token = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not hmac.compare_digest(token, _webhook_secret()):
        return jsonify({"ok": False}), 403
    # A cold start can take a few seconds: wait for the bot before accepting the update,
    # otherwise Telegram would consider it delivered and the message would be lost.
    if not bot_runner.ready.wait(timeout=50) or bot_runner.error:
        return jsonify({"ok": False, "error": "bot not ready"}), 503
    payload = request.get_json(silent=True, force=True)
    if not payload:
        return jsonify({"ok": False}), 400
    bot_runner.feed(payload)
    return jsonify({"ok": True})


@app.route("/healthz")
def healthz():
    """For UptimeRobot / cron-job.org pings that keep the free instance awake."""
    bot_runner = get_runner()
    status = "starting"
    if bot_runner.mode == "off":
        status = "off"
    elif bot_runner.error:
        status = "error"
    elif bot_runner.ready.is_set():
        status = "online"
    # Always 200 so the hosting health check never restarts the web panel because of the bot.
    return jsonify({"ok": status != "error", "web": "online", "bot": status, "mode": bot_runner.mode,
                    "stage": bot_runner.stage, "pid": bot_runner.pid,
                    "bot_error": (bot_runner.error or "")[:200] or None})


if __name__ == "__main__":
    get_runner()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), use_reloader=False)

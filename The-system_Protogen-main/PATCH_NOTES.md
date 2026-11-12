# Protogen bot fixes

- Added safe local SQLite fallback for the Flask web panel when DATABASE_URL is not configured.
- Replaced the hardcoded Flask SECRET_KEY fallback with an ephemeral local secret.
- Made SESSION_COOKIE_SECURE configurable so local HTTP login works while Railway stays secure by default.
- Added UTF-8 console handling to prevent Windows cp1251 crashes on Russian/emoji logs.
- Added a clear BOT_TOKEN startup error for the Telegram worker.
- Fixed PostgreSQL-only ADD COLUMN IF NOT EXISTS migrations so local SQLite startup works.

Validation:
- Python compileall: OK
- Flask app import with local SQLite: OK
- Telegram worker import: OK
- Missing-token startup guard: OK

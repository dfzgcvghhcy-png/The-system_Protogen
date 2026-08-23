# Role access for ProtogenAdmin

The web panel now has three access levels:

- **Модератор** — only `Главная` and `Пользователи`. The Command Center / quick-actions panel is locked.
- **Администратор** — `Главная`, `Пользователи`, `Статистика`, `Настройки` in read-only mode. History and Command Center are locked. Any attempt to change a setting plays the supplied access-denied sound and the server rejects the POST request too.
- **Создатель** — full access to everything, including History, Command Center, wallpaper/admin actions, and changing settings.

## Railway Variables

Keep the existing creator credentials if you already use them:

```text
ADMIN_USERNAME=creator_login
ADMIN_PASSWORD=creator_password
```

Or use the explicit creator names:

```text
CREATOR_USERNAME=creator_login
CREATOR_PASSWORD=creator_password
```

For the Administrator account add:

```text
PANEL_ADMIN_USERNAME=admin_login
PANEL_ADMIN_PASSWORD=admin_password
```

For the Moderator account add:

```text
MODERATOR_USERNAME=moderator_login
MODERATOR_PASSWORD=moderator_password
```

Do not reuse the same username/password for different roles.

The existing `ADMIN_USERNAME` + `ADMIN_PASSWORD` pair remains the creator account for backward compatibility, so the current panel login will not stop working.

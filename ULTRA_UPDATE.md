# Protogen Ultra — combined update

Added in one release:

## Moderation
- /warn, /warns, /unwarn, /clearwarns
- /mute, /tempmute, /unmute
- /ban, /tempban, /unban
- /kick, /del, /clear, /purge
- /banlist, /mutelist
- rank hierarchy protection
- PostgreSQL command permission matrix

## Users & analytics
- /whois, /id, /history
- /stats, /top

## Tools
- /bookmark, /bookmarks
- /note, /notes
- /timer

## Protection
- Anti-Flood
- Anti-Links
- Anti-Invites
- Anti-CAPS
- Anti-Repeat
- Anti-Raid detection
- configurable action after Warn limit

## Social / fun
- /welcome, /rules
- /reputation, /plus
- /reward, /rewards
- /dice, /8ball, /random, /choose, /ship, /weather

## AI
Existing explicit /// triggers are preserved. Ordinary words like "Протоген" do not trigger AI.

## Web
The Moderation Control Center remains the place to enable/disable automation and set minimum command ranks. Creator-only changes are protected server-side.

### Important
`APScheduler==3.10.4` was added for persistent temporary mute/ban timers.


## 2026-08-26 — Iris social/RP block
- Added reputation ranking and Iris-style `+N`, `-N`, `*N` reply reactions with daily per-target protection.
- Added star reputation and star leaderboard.
- Added reward removal and moderator icon customization.
- Added join/leave notification switches and `+Правила` rule installation.
- Added safe 0+ RP actions: `Пожать руку`, `Обнять`, `Дать пять`, `Помахать`, `Похлопать`, `Подмигнуть`, `Поклониться`.
- Added ban voting with inline buttons: `Гб`, `Гб инфо`, `Гб стоп`, `Гб список`, plus `/gb*` aliases.
- New PostgreSQL tables are created automatically on startup.

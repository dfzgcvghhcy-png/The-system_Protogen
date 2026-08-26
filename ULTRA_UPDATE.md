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

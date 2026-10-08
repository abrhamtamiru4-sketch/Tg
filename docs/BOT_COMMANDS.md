# Bot Command Reference

All commands require admin status (your Telegram ID in `ADMIN_IDS`).

---

## Navigation

| Command | Description |
|---|---|
| `/start` | Open the ⚡ Control Center with full navigation keyboard |
| `/help` | Dynamic help message showing all enabled features |
| `/status` | Live system health: Telegram API, DB, Redis, AI |

---

## Content

| Command | Description |
|---|---|
| `/newpost` | Launch the interactive post composer |
| `/posts` | List 10 most recent posts with status |

### Post Composer Flow
```
/newpost
  → Select type: Text / Photo / Video / Audio / Document / Animation / Poll / Album
  → Send content (text, media, poll data)
  → Select target channels (tap to toggle)
  → Done → Preview shown
  → Choose: 🚀 Publish Now / 📅 Schedule / 💾 Draft / ✏️ Edit / 📋 Duplicate
```

### Poll Format
Send poll data as:
```
Your question text here
Option A
Option B
Option C
```

---

## Channels & Groups

| Command | Description |
|---|---|
| `/channels` | List all configured channels with permission status |

---

## Scheduling

| Command | Description |
|---|---|
| `/schedule` | View upcoming scheduled posts |
| `/queue` | Job queue status (pending / running / success / failed / dead) |

---

## System

| Command | Description |
|---|---|
| `/pause` | Pause all publishing (posts wait in queue) |
| `/resume` | Resume publishing (queued posts run immediately) |
| `/analytics` | Summary: total posts, published, failed, events |
| `/settings` | Current configuration (timezone, mode, log level) |

---

## Inline Mode

Type `@yourbotname` in any chat, then a search query:

```
@yourbotname digital art
```

Returns matching posts and templates you can insert directly.

Requires inline mode enabled via @BotFather (`/setinline`).

---

## Callback Actions

These appear as buttons after various commands:

| Button | Action |
|---|---|
| 🚀 Publish Now | Enqueue post for immediate publishing |
| 📅 Schedule | Set publish date/time |
| 💾 Draft | Save as draft |
| ✏️ Edit | Edit post content |
| 📋 Duplicate | Create a copy |
| 🗑 Delete | Archive the post |
| ✓ Verify | Re-check bot permissions in channel |
| 🔄 Refresh | Reload status |

---

## Error Messages

| Error | Cause | Fix |
|---|---|---|
| `Bot lacks 'can_post_messages'` | Bot not admin or missing permission | Promote bot to admin with Post Messages |
| `Chat not found` | Channel ID/username wrong | Verify the channel ID |
| `Telegram rate limit` | Too many messages | Auto-retried with backoff |
| `Duplicate post detected` | Same content already published | Edit content or use "Publish anyway" |
| `Pre-flight failed` | Content/permission issue | Read the check list for details |

---

## DRY RUN Mode

When `DRY_RUN=true`:
- Bot responds normally to all commands
- Posts are created and validated
- **No real Telegram messages are sent**
- Simulated results are logged
- Shown as `⚠ DRY RUN` indicator in /start and /status

Useful for testing without polluting channels.

# ⚡ Telegram Publisher

> Production-grade Telegram publishing platform with AI assistance, multi-channel scheduling, automation, and a premium dashboard.

**Bot API Version:** 10.3 (August 24, 2026)  
**Python:** 3.11+  
**Stack:** aiogram · FastAPI · PostgreSQL · Redis · Celery

---

## Features

| Category | Capabilities |
|---|---|
| **Publishing** | Text, Photo, Video, Audio, Document, Animation, Voice, Sticker, Albums, Polls, Rich Messages (API 10.1+) |
| **Scheduling** | One-time, Recurring (cron), Campaign schedules, Blackout windows, Timezone-aware |
| **Multi-channel** | One post → N channels/groups/topics, per-channel customization |
| **AI Assistant** | Generate, Rewrite, Summarize, Translate, A/B variants (OpenAI / Anthropic) |
| **Automation** | WHEN/IF/THEN rule engine, RSS triggers, webhook triggers |
| **Deduplication** | Exact hash, Normalized, Jaccard similarity, Perceptual hash (images) |
| **Queue** | Priority queue, Retry with backoff, Dead-letter, Idempotency keys |
| **Security** | JWT auth, RBAC (8 roles), Webhook validation, CSRF, SSRF protection |
| **Analytics** | Events tracking, Campaign performance, Reaction tracking |
| **Dashboard** | Dark/light mode, Responsive, Live preview, Preflight checker |
| **Bot API 10.3** | Disabled buttons, Rich Message buttons, Expandable quote blocks |
| **Bot API 10.2** | Ephemeral messages, Communities |
| **Bot API 10.1** | Rich Messages (paragraphs, tables, collages, slideshows) |
| **Bot API 10.0** | Live Photos, Guest Mode, Reactions bulk delete |

---

## Quick Start

### Option A: Docker (recommended)

```bash
git clone <your-repo>
cd telegram_publisher

cp .env.example .env
# Edit .env: set BOT_TOKEN and ADMIN_IDS

docker compose up -d
```

Access the dashboard at `http://localhost:8000` (or your server IP).

### Option B: Local / Termux (Android)

```bash
bash scripts/setup.sh

# Start the bot (long-polling mode)
python backend/bot_main.py

# Start the API server (separate terminal)
uvicorn backend.main:app --reload --port 8000
```

### Option C: VPS (Ubuntu 22.04+)

```bash
bash scripts/setup.sh
# Then run with systemd or tmux — see DEPLOYMENT.md
```

---

## Configuration

All settings go in `.env`. Required:

```env
BOT_TOKEN=<from @BotFather>
ADMIN_IDS=<your Telegram user ID>
DATABASE_URL=<postgresql+asyncpg://... or sqlite+aiosqlite:///./publisher.db>
```

See `.env.example` for all options.

---

## Architecture

```
┌─────────────────────────────────────┐
│          Web Dashboard              │  frontend/index.html
└────────────────┬────────────────────┘
                 │ REST API
┌────────────────▼────────────────────┐
│          FastAPI Server             │  backend/main.py
│   /api/v1/* · /webhook · /health   │
└──────┬─────────────┬────────────────┘
       │             │
┌──────▼──────┐ ┌────▼──────┐
│  PostgreSQL │ │   Redis   │
└──────┬──────┘ └────┬──────┘
       │             │
┌──────▼─────────────▼──────────────┐
│         Celery Worker Pool        │
│  publisher · scheduler · source   │
│  ai · analytics · media           │
└───────────────────────────────────┘
       │
┌──────▼──────────────────────────────┐
│     TelegramClient (aiogram)        │
│  Rate limiter · Capability registry │
│  Permission engine · Retry logic    │
└─────────────────────────────────────┘
```

---

## Telegram Bot API 10.3 — Capability Status

| Capability | Status | Notes |
|---|---|---|
| sendMessage | ✅ Official | Core text messaging |
| sendPhoto/Video/Audio | ✅ Official | All media types |
| sendMediaGroup | ✅ Official | Up to 10 items |
| sendRichMessage | ✅ API 10.1+ | Blocks: tables, collages, slideshows |
| sendEphemeralMessage | ✅ API 10.2+ | Visible to one user only |
| Disabled buttons | ✅ API 10.3 | Greyed-out inline buttons |
| Rich message buttons | ✅ API 10.3 | Buttons on rich messages |
| Communities | ✅ API 10.2 | Supergroups + channels |
| Guest mode | ✅ API 10.0 | Respond without membership |
| Live Photos | ✅ API 10.0 | sendLivePhoto |
| message_views | ❌ Unavailable | Not exposed by Bot API |
| read_messages | ❌ Unavailable | Bots cannot read history |

---

## Project Structure

```
telegram_publisher/
├── backend/
│   ├── main.py                   # FastAPI app
│   ├── bot_main.py               # Telegram bot
│   └── app/
│       ├── core/                 # Config, security, feature flags
│       ├── telegram/             # API client, capability registry
│       ├── db/                   # Models, migrations
│       ├── api/                  # REST routers
│       ├── bot/                  # Bot handlers
│       ├── services/             # Business logic
│       └── workers/              # Celery tasks
├── frontend/
│   └── index.html                # Dashboard SPA
├── docker/
│   ├── Dockerfile
│   └── nginx.conf
├── docs/                         # Documentation
├── scripts/
│   └── setup.sh
├── docker-compose.yml
├── alembic.ini
├── pyproject.toml
└── .env.example
```

---

## Security

- All secrets in `.env` — never committed
- JWT authentication for web API
- Webhook secret validation (X-Telegram-Bot-Api-Secret-Token)
- HMAC-signed callback data
- SSRF protection on source URLs
- Prompt injection sanitisation for imported content
- RBAC with 8 roles (Owner → Viewer)
- Idempotency keys prevent duplicate publishing
- Audit log for all admin actions

---

## License

MIT — see LICENSE file.

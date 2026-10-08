# Installation Guide

## Prerequisites

| Tool | Minimum Version | Notes |
|---|---|---|
| Python | 3.11 | Required |
| pip | 23+ | `pip install --upgrade pip` |
| PostgreSQL | 14+ | Or use SQLite for dev/Termux |
| Redis | 6+ | Optional in Termux (in-process fallback) |
| Docker | 24+ | Optional — for containerized deployment |

---

## Step 1 — Get a Bot Token

1. Open Telegram, search for **@BotFather**
2. Send `/newbot` and follow the prompts
3. Copy the token — it looks like `123456789:ABCdef...`
4. Send `/setinline` → enable inline mode
5. Send `/setcommands` (optional — the app sets commands automatically)

## Step 2 — Get Your Telegram User ID

Send any message to **@userinfobot** or **@getidsbot**.  
Your numeric ID (e.g. `987654321`) goes in `ADMIN_IDS`.

---

## Environment A — Docker (Production)

```bash
# 1. Clone the repository
git clone https://github.com/yourname/telegram-publisher
cd telegram-publisher

# 2. Configure environment
cp .env.example .env
nano .env   # Set BOT_TOKEN and ADMIN_IDS at minimum

# 3. Start all services
docker compose up -d

# 4. Run database migrations
docker compose exec api python -m alembic upgrade head

# 5. Check health
curl http://localhost:8000/health
curl http://localhost:8000/ready

# 6. Send /start to your bot in Telegram
```

Services started by `docker compose up -d`:
- **bot** — Telegram bot process
- **api** — FastAPI REST server on port 8000
- **worker** — Celery publisher/media/analytics workers
- **scheduler** — Celery beat + scheduler/source/AI workers
- **postgres** — PostgreSQL 16
- **redis** — Redis 7

---

## Environment B — VPS / Bare Metal (Ubuntu 22.04+)

```bash
# 1. System deps
sudo apt update && sudo apt install -y \
    python3.11 python3.11-venv python3-pip \
    postgresql postgresql-contrib redis-server \
    libpq-dev gcc nginx

# 2. Database setup
sudo -u postgres psql -c "CREATE USER publisher WITH PASSWORD 'changeme';"
sudo -u postgres psql -c "CREATE DATABASE telegram_publisher OWNER publisher;"

# 3. Redis (start and enable)
sudo systemctl enable --now redis-server

# 4. Clone and install
git clone https://github.com/yourname/telegram-publisher
cd telegram-publisher
python3.11 -m venv venv && source venv/bin/activate
pip install -e "."

# 5. Configure
cp .env.example .env && nano .env
# Set DATABASE_URL=postgresql+asyncpg://publisher:changeme@localhost/telegram_publisher

# 6. Migrate
python -m alembic upgrade head

# 7. Install systemd services
sudo cp scripts/systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now publisher-bot publisher-api publisher-worker publisher-scheduler

# 8. Nginx reverse proxy
sudo cp docker/nginx.conf /etc/nginx/sites-available/publisher
sudo ln -s /etc/nginx/sites-available/publisher /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

---

## Environment C — Termux (Android)

Termux runs the bot in lightweight mode: SQLite instead of PostgreSQL,
in-process APScheduler instead of Celery, no Redis required.

```bash
# 1. Install packages in Termux
pkg update && pkg install python git

# 2. Clone
git clone https://github.com/yourname/telegram-publisher
cd telegram-publisher

# 3. Auto setup (detects Termux, uses SQLite)
bash scripts/setup.sh

# 4. Edit config
nano .env
# BOT_TOKEN=your_token_here
# ADMIN_IDS=your_telegram_id
# DATABASE_URL=sqlite+aiosqlite:///./publisher.db

# 5. Start
python backend/bot_main.py

# Optional: also start the API dashboard
uvicorn backend.main:app --host 0.0.0.0 --port 8000 &
# Then open http://localhost:8000 in your phone browser
```

To keep running after Termux closes:
```bash
# Install termux-services
pkg install termux-services

# Or use tmux
pkg install tmux
tmux new -s publisher
python backend/bot_main.py
# Ctrl+B, D to detach
```

---

## Environment D — Railway / Render / Fly.io

### Railway

```bash
# Install Railway CLI
npm install -g @railway/cli

# Login and create project
railway login
railway init

# Add PostgreSQL and Redis plugins in Railway dashboard

# Set environment variables
railway variables set BOT_TOKEN=... ADMIN_IDS=...

# Deploy
railway up
```

### Fly.io

```bash
# Install flyctl
curl -L https://fly.io/install.sh | sh

# Launch app
fly launch --name telegram-publisher

# Set secrets
fly secrets set BOT_TOKEN=... ADMIN_IDS=...

# Deploy
fly deploy
```

---

## Step — Set Webhook (Production Only)

If `WEBHOOK_URL` is set in `.env`, the bot automatically registers it on startup.

Manual registration:
```bash
curl "https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://yourdomain.com/webhook&secret_token=<YOUR_SECRET>"
```

To verify:
```bash
curl "https://api.telegram.org/bot<TOKEN>/getWebhookInfo"
```

For development and Termux, leave `WEBHOOK_URL=` empty to use long-polling.

---

## Verify Installation

```bash
# 1. Health endpoint
curl http://localhost:8000/health
# → {"status": "ok", "dry_run": false}

# 2. Readiness (all services)
curl http://localhost:8000/ready
# → {"status": "ready", "checks": {"database": "ok", "telegram": "ok", ...}}

# 3. API version info
curl http://localhost:8000/version
# → {"version": "1.0.0", "telegram_api_version": "10.3", ...}

# 4. Open Telegram and send /start to your bot
# → Should respond with the Control Center keyboard

# 5. Dashboard
# Open http://localhost:8000 or your server URL
```

---

## Common Issues

**Bot doesn't respond:**
- Verify `BOT_TOKEN` is correct (no extra spaces)
- In polling mode: ensure only one bot process is running
- In webhook mode: ensure `WEBHOOK_URL` is publicly reachable HTTPS

**Database connection refused:**
- PostgreSQL: check `DATABASE_URL` credentials
- Termux: make sure `DATABASE_URL` starts with `sqlite+aiosqlite://`

**`ModuleNotFoundError`:**
```bash
export PYTHONPATH=/path/to/telegram_publisher/backend
# or run from the project root
```

**Redis connection refused (non-Termux):**
```bash
redis-cli ping  # should return PONG
# If not: sudo systemctl start redis-server
```

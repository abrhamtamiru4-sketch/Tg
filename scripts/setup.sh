#!/usr/bin/env bash
# ╔══════════════════════════════════════════════════════════╗
# ║  Telegram Publisher — One-command setup script          ║
# ║  Works on: Ubuntu/Debian VPS, macOS, Termux (Android)  ║
# ╚══════════════════════════════════════════════════════════╝
set -euo pipefail

BOLD='\033[1m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'

info()    { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }
success() { echo -e "${GREEN}[✓]${NC} $*"; }
error()   { echo -e "${RED}[✗]${NC} $*"; exit 1; }

# ── Detect environment ────────────────────────────────────────
is_termux() { [[ -n "${TERMUX_VERSION:-}" ]] || [[ -d "/data/data/com.termux" ]]; }
is_docker() { [[ -f "/.dockerenv" ]]; }

echo ""
echo -e "${BOLD}╔══════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║  Telegram Publisher Setup                 ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════╝${NC}"
echo ""

# ── Check Python ─────────────────────────────────────────────
if command -v python3 &>/dev/null; then
    PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
    success "Python $PYTHON_VERSION found"
else
    error "Python 3.11+ is required. Install it first."
fi

# ── Check Python version ──────────────────────────────────────
MIN_PYTHON="3.11"
if python3 -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)" 2>/dev/null; then
    success "Python version OK"
else
    error "Python 3.11+ required. Got $PYTHON_VERSION"
fi

# ── Create .env from example ──────────────────────────────────
if [[ ! -f ".env" ]]; then
    cp .env.example .env
    warn ".env created from .env.example"
    warn "IMPORTANT: Edit .env and set BOT_TOKEN and ADMIN_IDS before starting!"
    echo ""
    echo "  Required settings:"
    echo "    BOT_TOKEN=<your token from @BotFather>"
    echo "    ADMIN_IDS=<your Telegram user ID>"
    echo ""
else
    success ".env already exists"
fi

# ── Install Python dependencies ────────────────────────────────
info "Installing Python packages..."

if is_termux; then
    warn "Termux detected — using SQLite mode (lightweight)"
    # SQLite + no Redis for Termux
    pip install --quiet \
        aiogram fastapi "uvicorn[standard]" pydantic pydantic-settings \
        sqlalchemy[asyncio] alembic aiosqlite \
        passlib[bcrypt] python-jose[cryptography] \
        httpx aiofiles feedparser bleach jinja2 \
        python-dotenv structlog tenacity pytz shortuuid xxhash croniter 2>&1 | tail -5
    
    warn "Note: Celery workers are disabled in Termux mode."
    warn "      Scheduling runs in-process via APScheduler."
    
    # Override DATABASE_URL for SQLite
    if grep -q "^DATABASE_URL=postgresql" .env 2>/dev/null; then
        sed -i 's|^DATABASE_URL=postgresql.*|DATABASE_URL=sqlite+aiosqlite:///./publisher.db|' .env
        warn "DATABASE_URL switched to SQLite for Termux"
    fi
else
    pip install --quiet -e ".[dev]" 2>&1 | tail -5
fi

success "Python packages installed"

# ── Run database migrations ────────────────────────────────────
info "Setting up database..."
if [[ -f ".env" ]]; then
    set -a; source .env; set +a
fi

# Use create_all for SQLite (no Alembic needed in dev)
if [[ "${DATABASE_URL:-}" == *"sqlite"* ]]; then
    python3 -c "
import asyncio
import sys
sys.path.insert(0, 'backend')
from app.db.session import create_all_tables
asyncio.run(create_all_tables())
print('SQLite tables created.')
" && success "Database tables created (SQLite)"
else
    python3 -m alembic upgrade head && success "Migrations applied (PostgreSQL)"
fi

# ── Generate secret key ───────────────────────────────────────
if grep -q "CHANGE_ME_IN_PRODUCTION" .env 2>/dev/null; then
    NEW_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
    sed -i "s|SECRET_KEY=CHANGE_ME_IN_PRODUCTION_USE_64_RANDOM_HEX_CHARS|SECRET_KEY=${NEW_SECRET}|" .env
    success "SECRET_KEY generated"
fi

# ── Check BOT_TOKEN ───────────────────────────────────────────
if grep -q "^BOT_TOKEN=123456" .env 2>/dev/null; then
    echo ""
    warn "⚠  BOT_TOKEN is still the placeholder!"
    warn "   Edit .env and set your real token from @BotFather."
    echo ""
else
    success "BOT_TOKEN configured"
fi

echo ""
echo -e "${BOLD}Setup complete! 🚀${NC}"
echo ""
echo "To start the bot:"
echo ""
if is_termux; then
    echo "  python backend/bot_main.py"
    echo ""
    echo "To also start the API server:"
    echo "  uvicorn backend.main:app --reload --port 8000"
else
    echo "  # Docker (recommended):"
    echo "  docker compose up -d"
    echo ""
    echo "  # Or directly:"
    echo "  python backend/bot_main.py       # Bot"
    echo "  uvicorn backend.main:app --port 8000  # API"
    echo "  celery -A backend.app.workers.celery_app.celery worker  # Workers"
fi
echo ""

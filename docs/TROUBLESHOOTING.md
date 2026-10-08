# Troubleshooting Guide

## Bot Doesn't Respond

**Check 1: Bot token valid?**
```bash
curl "https://api.telegram.org/bot<YOUR_TOKEN>/getMe"
# Should return: {"ok":true,"result":{"username":"yourbot",...}}
```
If it returns `{"ok":false}`, the token is wrong. Get a new one from @BotFather.

**Check 2: Only one instance running?**
In polling mode, only one process can poll at a time.
```bash
ps aux | grep bot_main
# Kill duplicates: kill <PID>
```

**Check 3: Bot process is running?**
```bash
# Docker
docker compose logs bot --tail=50

# Direct
python backend/bot_main.py
# Should print: "bot_started username=yourbot"
```

**Check 4: Admin ID correct?**
Send a message to @userinfobot — get your exact numeric ID.
Make sure it matches `ADMIN_IDS` in `.env`.

---

## Database Errors

**`asyncpg.exceptions.ConnectionDoesNotExistError`**
```bash
# PostgreSQL not running:
docker compose up -d postgres
# Or:
sudo systemctl start postgresql
```

**`sqlalchemy.exc.OperationalError: no such table`**
```bash
# Run migrations:
python -m alembic upgrade head
# Or for SQLite dev mode:
python -c "import asyncio; from app.db.session import create_all_tables; asyncio.run(create_all_tables())"
```

**`UNIQUE constraint failed`**
Attempted to insert a duplicate idempotency key.
This is expected behaviour — the job was already processed. Check the logs:
```bash
grep "idempotency_violation" logs/publisher.log
```

---

## Redis Errors

**`redis.exceptions.ConnectionError`**
```bash
# Check Redis is running:
redis-cli ping  # Should print PONG

# Docker:
docker compose up -d redis

# Termux: Redis not supported
# → The app falls back to in-process memory storage automatically
```

**`celery.exceptions.TimeoutError`**
```bash
# Check worker is running:
docker compose logs worker --tail=30

# Restart worker:
docker compose restart worker
```

---

## Posts Not Publishing

**Check the job status:**
```
/queue   (in Telegram)
```
Or in dashboard → Queue.

**Common causes:**

| Status | Cause | Fix |
|---|---|---|
| `dead` | Max retries exceeded | Check `error_message` in dashboard |
| `failed` | Telegram API error | Usually permission or content issue |
| `pending` | Worker not running | Start Celery worker |
| `retrying` | Temporary error | Wait — will retry automatically |

**Check logs:**
```bash
docker compose logs worker --tail=100 | grep "post_id"
```

**Pre-flight failed:**
Use the dashboard → Posts → Preflight to see exactly which check failed.
Or via bot: `/posts` → tap the post → check the status message.

---

## Permission Errors

**`Bot lacks 'can_post_messages'`**

In Telegram:
1. Open your channel
2. Settings → Administrators → tap your bot
3. Enable ✓ Post Messages
4. In dashboard: Channels → Verify

**`Bot is NOT an administrator`**

1. Open channel/group settings
2. Add bot as administrator
3. Run `/channels` → Verify

---

## AI Not Working

**`Feature 'AI' is disabled`**
```env
# In .env:
FEATURE_AI=true
AI_PROVIDER=openai       # or anthropic
OPENAI_API_KEY=sk-...    # your key
```

**`OpenAI error: 429 Too Many Requests`**
You've hit the rate limit on your OpenAI plan. Reduce AI usage or upgrade.

**Output quality poor:**
Try `AI_MODEL=gpt-4o` instead of `gpt-4o-mini` for better quality.

---

## Webhook Issues

**`403 Forbidden` from webhook:**
Check `WEBHOOK_SECRET` matches what you registered with Telegram.

**Bot not receiving updates via webhook:**
```bash
# Check webhook info:
curl "https://api.telegram.org/bot<TOKEN>/getWebhookInfo"
# Look for "last_error_message" — that's the problem

# Must be HTTPS with valid cert:
# - Let's Encrypt: sudo certbot --nginx
# - Or disable webhook, use polling: WEBHOOK_URL= (empty)
```

**Switch to polling (simpler):**
```env
WEBHOOK_URL=   # leave empty
```
Restart the bot — it will use long-polling automatically.

---

## DRY RUN Mode

If you enabled dry run and posts show as "Published" but nothing appeared in channels:
```env
DRY_RUN=false   # Set to false in .env
```
Restart all services.

---

## Performance Issues

**Slow publishing:**
- Add more publisher workers: `docker compose up -d --scale worker=4`
- Check Redis latency: `redis-cli --latency`
- Check PostgreSQL slow queries: `pg_stat_activity`

**High memory:**
- Reduce `worker_prefetch_multiplier` in Celery config (default: 1)
- Check media worker isn't loading large files unnecessarily

---

## Getting Logs

```bash
# Docker — all services
docker compose logs --tail=100 -f

# Specific service
docker compose logs bot --tail=100
docker compose logs worker --tail=100

# Structured JSON logs (production)
docker compose logs api | python -m json.tool

# Bot process directly
PYTHONPATH=backend python backend/bot_main.py 2>&1 | tee bot.log
```

---

## UPGRADE.md

## Upgrading

### Minor version update (1.x.y → 1.x.z)

```bash
git pull origin main
pip install -e "."               # Update dependencies
python -m alembic upgrade head   # Apply new migrations
docker compose up -d --build     # Docker: rebuild and restart
```

### Adding a new Telegram Bot API version

When Telegram releases a new Bot API version (e.g. 10.4):

1. Update `telegram_api_version` in `.env`:
   ```env
   # Not needed — controlled by the registry
   ```

2. Add new capabilities to `capability_registry.py`:
   ```python
   TelegramCapability(
       name="new_feature",
       telegram_method="newMethod",
       status=CapabilityStatus.VERSIONED,
       min_bot_api_version="10.4",
   )
   ```

3. Add a feature flag if experimental:
   ```python
   flags.register(FeatureFlag("NEW_FEATURE", "Description", default=False, min_api_version="10.4"))
   ```

4. Implement in `TelegramClient` if needed

5. Add tests

6. Enable the flag: `FEATURE_NEW_FEATURE=true` in `.env`

The capability registry ensures no existing functionality breaks.

### Rollback

```bash
# Roll back last migration
python -m alembic downgrade -1

# Roll back to specific revision
python -m alembic downgrade 0001_initial

# Docker: roll back image
docker compose up -d --scale api=0
docker tag <previous_image> telegram-publisher_api:latest
docker compose up -d api
```

### Database backup

```bash
# PostgreSQL backup
docker compose exec postgres pg_dump -U postgres telegram_publisher > backup_$(date +%Y%m%d).sql

# Restore
docker compose exec -T postgres psql -U postgres telegram_publisher < backup_20261001.sql

# SQLite backup
cp publisher.db publisher.db.bak
```

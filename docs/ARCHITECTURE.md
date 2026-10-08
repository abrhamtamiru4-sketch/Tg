# Architecture

## System Overview

```
                  ┌─────────────────────────┐
                  │   Telegram Users/Admins │
                  └────────────┬────────────┘
                               │ HTTPS
              ┌────────────────┼────────────────┐
              │                │                │
       ┌──────▼──────┐  ┌──────▼──────┐  ┌─────▼──────┐
       │  Bot (Poll/ │  │  Webhook    │  │  Dashboard │
       │  Webhook)   │  │  Receiver   │  │  (Browser) │
       └──────┬──────┘  └──────┬──────┘  └─────┬──────┘
              │                │                │
              └────────────────▼────────────────┘
                        ┌──────────────┐
                        │  FastAPI     │
                        │  REST API   │
                        └──────┬───────┘
                               │
            ┌──────────────────┼──────────────────┐
            │                  │                  │
     ┌──────▼──────┐   ┌───────▼──────┐  ┌───────▼──────┐
     │ PostgreSQL  │   │    Redis     │  │  Media Store │
     │  (Primary)  │   │  (Queue +   │  │  (Local/S3)  │
     │             │   │   Cache)    │  │              │
     └─────────────┘   └──────┬──────┘  └──────────────┘
                              │
                  ┌───────────▼────────────┐
                  │    Celery Worker Pool  │
                  ├────────────────────────┤
                  │ publisher (priority 7) │
                  │ scheduler (beat + q)  │
                  │ source  (RSS fetch)   │
                  │ ai      (generation)  │
                  │ analytics (tracking)  │
                  │ media   (processing)  │
                  └────────────┬───────────┘
                               │
                  ┌────────────▼───────────┐
                  │    TelegramClient      │
                  ├────────────────────────┤
                  │ CapabilityRegistry     │
                  │ RateLimiter            │
                  │ PermissionEngine       │
                  │ RetryableRequest       │
                  └────────────────────────┘
```

---

## Core Design Principles

### 1. Zero-Hallucination API Policy
Every Telegram Bot API capability is explicitly registered in `TelegramCapabilityRegistry`.
The registry is the single source of truth for:
- Which methods exist
- Their minimum API version
- Their availability status
- Fallback behaviour when unavailable

No Telegram API call exists outside `TelegramClient`. No fake methods. No invented parameters.

### 2. Idempotency
Every publish job has a deterministic idempotency key:
```python
key = SHA256(f"publish:{post_id}:{target_id}:{schedule_bucket}")
```
If the same job fires twice (crash, retry, bug), the second execution is a no-op.

### 3. Pre-flight → Publish → Verify
Every publish passes three gates:
1. **Pre-flight** — Validates content, permissions, duplicates *before* sending
2. **Publish** — Single Telegram API call via `TelegramClient`
3. **Post-verify** — Confirms message_id received, stores result, updates analytics

### 4. Non-crashing Errors
No error can crash the entire system:
- Retryable errors → exponential backoff → dead-letter after N attempts
- Non-retryable → immediate dead-letter + admin notification
- Database outage → jobs wait in Redis
- AI outage → publishing continues without AI features
- Redis outage → in-memory queue fallback (development only)

### 5. Future-Proof Adapter Pattern
```
TelegramCapabilityRegistry
├── OfficialCapabilities    — documented, stable, implemented
├── VersionedCapabilities   — available from min_api_version
├── ExperimentalCapabilities — behind feature flag
├── FutureCapabilities      — adapter placeholder, not yet released
└── UnsupportedCapabilities — confirmed unavailable, with fallback
```

When Telegram releases Bot API 10.4+:
1. Add capability to registry
2. Set `min_bot_api_version`
3. Add feature flag if experimental
4. Write tests
5. No existing code changes required

---

## Data Flow: Post Lifecycle

```
User creates post (bot or dashboard)
        │
        ▼
   [DRAFT] → saved to posts table
        │
        ▼ (manual or workflow)
[PENDING_REVIEW] → notification sent to admins
        │
        ▼ (approved by admin)
    [APPROVED]
        │
        ├─── Scheduled? → Schedule record → Scheduler picks up → Job created
        │
        └─── Publish Now → Job created immediately
                                │
                                ▼
                         [Job Queue]
                                │
                                ▼
                     PreflightValidator.validate()
                       • Target accessible?
                       • Bot has permissions?
                       • Content valid?
                       • Idempotency key unique?
                                │
                            PASS │ FAIL → [FAILED] + notify admin
                                │
                                ▼
                      Publisher.publish()
                       • Rate limiter acquire
                       • TelegramClient.send_*()
                       • RetryableRequest (5 attempts)
                                │
                            OK  │ Error → retry / dead-letter
                                │
                                ▼
                     Post-publish verification
                       • Store message_id
                       • Update status → [PUBLISHED]
                       • Record analytics event
                       • Write audit log
                       • Send admin notification
```

---

## Queue Architecture

```
Priority Queue (publisher)
  Priority 10 (CRITICAL) — urgent admin-triggered
  Priority 7  (HIGH)     — immediate publish
  Priority 5  (NORMAL)   — scheduled posts
  Priority 3  (LOW)      — AI generation, source fetch

Retry Queue      — failed jobs with countdown
Dead Letter Queue — exhausted all retries
Approval Queue   — pending human review
```

Every job record in the database has:
- `job_id` (UUID)
- `idempotency_key` (deterministic hash)
- `status` (pending → running → success/failed/retrying/dead)
- `attempts` + `max_attempts`
- `error_type` + `error_message`
- `result` (JSON — includes telegram_message_id on success)

---

## Security Architecture

```
Internet
    │
    ▼
Nginx (TLS termination, security headers)
    │
    ▼
FastAPI middleware stack:
  • Request ID injection
  • Security headers (CSP, HSTS, X-Frame-Options)
  • CORS (restricted in production)
  • Rate limiting (per-IP, per-user)
    │
    ├─── /webhook  → validate X-Telegram-Bot-Api-Secret-Token
    │
    ├─── /api/v1/* → JWT Bearer authentication
    │                 → RBAC role check
    │                 → Audit log write
    │
    └─── /health   → no auth required
```

### Secrets Never Logged
The `_redact_secrets()` structlog processor scrubs:
- Bot tokens (`\d{8,12}:[A-Za-z0-9_-]{35}`)
- Passwords, secrets, API keys (by keyword)
- Long uppercase credential strings

---

## Module Dependency Graph

```
core/config  ←── everything reads settings
     │
core/feature_flags ←── gates optional features
     │
core/security ←── JWT, hashing, signing
     │
core/exceptions ←── all domain errors
     │
telegram/capability_registry ←── single source of API truth
     │
telegram/rate_limiter ←── throttles all API calls
     │
telegram/client ←── wraps all Bot API calls
     │              uses: rate_limiter, capability_registry
     │
telegram/permission_engine ←── pre-publish permission check
     │
services/publishing/preflight ←── validates before send
services/publishing/publisher ←── orchestrates publish flow
     │
services/queue/ ←── job management
services/scheduler/ ←── cron evaluation
services/content/deduplication ←── duplicate detection
services/templates/engine ←── Jinja2 rendering
services/automation/rule_engine ←── WHEN/IF/THEN
services/ai/assistant ←── AI provider wrapper
services/notifications/ ←── admin alerts
     │
workers/ ←── Celery tasks (call services, not business logic)
     │
api/routers/ ←── HTTP endpoints (call services)
bot/handlers/ ←── Telegram handlers (call services)
```

---

## Scalability

Each worker type is independently scalable:

```bash
# Scale publisher workers for high volume
docker compose up -d --scale worker=4

# Scale scheduler separately (only 1 beat process!)
docker compose up -d --scale scheduler=1

# AI worker on a separate machine with GPU
docker compose -f docker-compose.ai.yml up -d ai-worker
```

Workers communicate only through Redis queues and PostgreSQL.
No direct worker-to-worker calls. Fully stateless.

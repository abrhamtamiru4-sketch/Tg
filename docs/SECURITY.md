# Security Guide

## Secrets Management

### Never commit to Git

`.gitignore` blocks:
```
.env
*.key
*.pem
media/
```

### Required in production

```env
SECRET_KEY=<64 random hex chars>  # python -c "import secrets; print(secrets.token_hex(32))"
BOT_TOKEN=<from BotFather>
WEBHOOK_SECRET=<random string>    # python -c "import secrets; print(secrets.token_urlsafe(32))"
DATABASE_URL=postgresql+asyncpg://user:strongpassword@host/db
```

### Rotate secrets

To rotate `SECRET_KEY`:
1. Generate new key: `python -c "import secrets; print(secrets.token_hex(32))"`
2. Update `.env`
3. Restart all services (existing JWTs are invalidated — users must re-login)

---

## Authentication

### Web Dashboard

JWT Bearer tokens (HS256). Access tokens expire in 24h, refresh tokens in 30d.

No unauthenticated access to `/api/v1/*`.

### Bot Commands

Admin allowlist: only Telegram user IDs in `ADMIN_IDS` can use admin commands.

```python
# All handlers check this before executing:
if message.from_user.id not in settings.admin_id_list:
    return  # silently ignore
```

### API Keys

Long-lived machine-to-machine tokens. Only the SHA-256 hash is stored in the database.
The raw key is shown once on creation.

---

## RBAC — Role-Based Access Control

| Role | Permissions |
|---|---|
| `owner` | Full access, manage other admins |
| `super_admin` | All publishing operations, manage settings |
| `admin` | Create, edit, publish, manage channels |
| `editor` | Create and edit posts, cannot publish |
| `publisher` | Publish approved posts, cannot edit |
| `moderator` | Moderate groups, manage join requests |
| `analyst` | Read-only analytics access |
| `viewer` | Read-only dashboard access |

Least-privilege: grant the minimum role needed.

---

## Webhook Security

Telegram sends a secret token in `X-Telegram-Bot-Api-Secret-Token` header.
The server validates it using constant-time comparison:

```python
hmac.compare_digest(header_value, settings.webhook_secret)
```

Set a strong random secret:
```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

---

## Callback Data Signing

Inline button callback data is signed with HMAC-SHA256:

```
original_data|first_12_chars_of_hmac
```

This prevents users from forging callback data to trigger unauthorized actions.

---

## SSRF Protection

External content sources (RSS, webhooks) are validated before fetching:

- Scheme must be `http` or `https`
- Hostname must resolve to a public IP
- Blocks: 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 127.0.0.0/8, 169.254.0.0/16
- Response size capped at 5 MB
- Timeout: 30 seconds

---

## Prompt Injection Protection

All imported content (RSS, webhooks) is sanitised before passing to AI:

```python
dangerous_patterns = [
    "ignore previous instructions",
    "system prompt",
    "you are now",
    "disregard",
]
# → Content wrapped in safety boundary tags
```

External content is never trusted to contain instructions.

---

## Input Validation

- All API inputs validated by Pydantic schemas
- HTML sanitised by `bleach` (RSS/imported content)
- SQL injection impossible (SQLAlchemy ORM, no raw queries)
- File uploads: content-type validated, size limited, stored outside web root
- Bot API entities validated before send

---

## Audit Logging

Every important action is recorded:

```json
{
  "action": "post_published",
  "user_id": 123,
  "role": "admin",
  "resource_type": "post",
  "resource_id": 456,
  "result": "success",
  "ip_address": "1.2.3.4",
  "created_at": "2026-10-01T12:00:00Z"
}
```

Audit logs are append-only. Never delete them.

---

## Security Headers (Nginx)

```nginx
add_header X-Content-Type-Options    "nosniff";
add_header X-Frame-Options           "DENY";
add_header X-XSS-Protection          "1; mode=block";
add_header Strict-Transport-Security "max-age=31536000; includeSubDomains";
add_header Referrer-Policy           "strict-origin-when-cross-origin";
```

---

## Dependency Scanning

```bash
# Check for known vulnerabilities
pip install pip-audit
pip-audit

# Or with Safety
pip install safety
safety check
```

Run in CI on every push.

---

## Suspicious Activity Detection

The system flags:
- Multiple failed authentication attempts
- Callback data with invalid signatures
- SSRF-blocked URL attempts
- Content with prompt injection patterns
- Jobs firing more than `max_attempts` times

All flagged events trigger admin notifications and audit log entries.

---

## Data at Rest

- Secrets in `.env` (file permissions: `chmod 600 .env`)
- PostgreSQL: enable `pg_hba.conf` authentication
- Redis: set `requirepass` in `redis.conf`
- Media files: store outside the web root, serve via authenticated URLs in production

---

## Checklist Before Go-Live

- [ ] Changed `SECRET_KEY` from placeholder
- [ ] Set strong `DATABASE_URL` password
- [ ] Set `WEBHOOK_SECRET` for webhook mode
- [ ] `DRY_RUN=false` in production `.env`
- [ ] `.env` not committed to Git (verify with `git status`)
- [ ] Nginx TLS configured with valid certificate
- [ ] `ADMIN_IDS` contains only intended administrator IDs
- [ ] `LOG_LEVEL=INFO` (not DEBUG — debug logs are verbose)
- [ ] Database backups configured (see DEPLOYMENT.md)
- [ ] Firewall: only ports 80, 443, and 22 open publicly

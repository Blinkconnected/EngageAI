# Security Hardening

M26 of the roadmap, opening Phase 6 (Hardening & Launch). An audit of
the existing security posture — built up incrementally since M1 — plus
the concrete gaps that audit found and closed: broader rate limiting,
security response headers, a CORS misconfiguration guard, and a
dependency vulnerability scan with real remediation.

## What was already solid (confirmed, not rebuilt)

- **SQL injection**: every repository uses SQLAlchemy Core/ORM
  `select()`/`insert()`/`update()` via parameterized queries. The only
  `text()` calls anywhere in `infrastructure/` are static, hardcoded
  partial-index predicates in model definitions (e.g.
  `Customer`/`Queue`/`Conversation`'s partial unique indexes) — no user
  input ever reaches a `text()` call. No f-string/`.format()`/`%`-built
  SQL exists anywhere in this codebase.
- **XSS**: this is a pure JSON API — no `HTMLResponse`, no template
  rendering anywhere in `src/`. XSS is the frontend's responsibility
  (out of scope for this backend-only build arc, see
  `docs/architecture/administration.md`).
- **CSRF**: authentication is bearer-JWT-only
  (`api/deps.py::get_current_auth` reads the `Authorization` header
  exclusively) — no cookie-based session exists anywhere in the
  codebase. CSRF specifically exploits ambient cookie auth; a bearer
  token that must be explicitly attached by the calling client isn't
  susceptible to the same cross-site forgery.
- **Password hashing**: `core/security.py` uses
  `CryptContext(schemes=["bcrypt"], deprecated="auto")` — bcrypt with
  passlib's standard cost factor, not a weaker/legacy scheme.
- **JWT verification**: `decode_token` passes an explicit
  `algorithms=[settings.jwt_algorithm]` allowlist to `jose.jwt.decode`,
  preventing algorithm-confusion (`alg: none`) attacks.
- **Secrets management**: `jwt_secret_key`/`credentials_encryption_key`
  are required settings with `min_length=32` and no default — the app
  refuses to boot without them. No hardcoded secrets exist anywhere in
  `src/`.
- **Encryption at rest**: `ChannelConfig`/`ErpConfig` credentials are
  encrypted via `infrastructure/security/crypto.py` — AES-256-GCM, a
  fresh random 12-byte nonce per encryption call (no nonce reuse).
- **Input validation**: Pydantic schemas consistently use
  `Field(min_length=..., max_length=...)`/`EmailStr`/custom validators
  (e.g. `schemas/validators.py::validate_password_strength`) as the
  system's input boundary.

## Gaps found and closed

### Rate limiting — extended beyond login/register

`core/rate_limit.py`'s `FixedWindowRateLimiter` already protected
`/auth/login`, `/auth/register`, and web-chat session creation. This
milestone extends it to:

- `/auth/refresh` and `/auth/logout` — previously unprotected token
  endpoints, now sharing the same `"auth"` scope/limit as login/register.
- `POST /csat/{id}/respond` — a public, unauthenticated endpoint (the
  token, not a role, authorizes it — see
  `docs/architecture/reports-analytics.md`), now rate limited per client
  IP like every other pre-auth public endpoint.
- Every `/ai/*` endpoint — a **new per-*user*** limiter
  (`api/deps.py::enforce_ai_rate_limit`, `settings.ai_rate_limit_per_minute`,
  default 20/minute), not per-IP. AI calls have a real external cost per
  call, and several agents can legitimately share one office IP, so
  throttling by authenticated identity (not client IP) is the correct
  unit here. This composition — an ``AuthContext``-aware rate limiter —
  lives in `api/deps.py`, not `core/rate_limit.py`, since `core/` must
  not depend on `api/` (the existing dependency-direction rule); it
  reuses `core/rate_limit.py`'s `FixedWindowRateLimiter`/
  `enforce_rate_limit` primitives directly.

### Security response headers

`core/security_headers.py`'s `SecurityHeadersMiddleware` adds, on every
response: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
`Referrer-Policy: strict-origin-when-cross-origin`,
`Permissions-Policy: geolocation=(), microphone=(), camera=()`. In
production only, it also adds
`Content-Security-Policy: default-src 'none'; frame-ancestors 'none'`
and `Strict-Transport-Security: max-age=63072000; includeSubDomains`.
The strict CSP is production-only because `/docs`/`/redoc` (Swagger
UI/ReDoc — real HTML pages loading JS/CSS from a CDN) are only ever
served outside production (`main.py` already sets `docs_url=None`/
`redoc_url=None` when `settings.is_production`) — applying it in dev
would break the very tool a developer is using it for.

### CORS misconfiguration guard

`main.py::create_app` now raises at startup if `settings.cors_allow_origins`
contains `"*"`. `allow_credentials=True` is required (so a browser client
can send its `Authorization` header) — combined with a wildcard origin,
the CORS spec actually forbids browsers from honoring the wildcard for
credentialed requests, which silently *looks* configured but isn't; a
loud startup failure is safer than a silent, confusing runtime
mismatch. Ships as-configured with an explicit origin allowlist
(`cors_allow_origins` defaults to `["http://localhost:5173"]`), so this
guard only fires on a genuine operator misconfiguration.

### Dependency vulnerability scan

`pip-audit` (newly added as a one-off scanning tool, not a runtime or
even a persistent dev dependency — run via `pip install pip-audit` when
needed) found 27 known vulnerabilities across 8 packages. Remediated:

| Package | Was | Now | Why |
|---|---|---|---|
| `python-jose` | 3.3.0 | 3.5.0 | JWT bomb DoS + algorithm-confusion CVEs in the library this app's entire auth model depends on — security-critical, fixed via a same-API patch bump (`jwt.encode`/`jwt.decode` signatures unchanged, verified). |
| `orjson` | 3.10.12 | 3.11.9 | Unbounded recursion on deeply-nested JSON during `dumps()` — patch bump, no API change. |
| `python-multipart` | 0.0.20 | 0.0.32 | Several parsing DoS/path-traversal CVEs (this app doesn't use the vulnerable `UPLOAD_DIR` option, but the parsing-DoS fixes apply regardless) — patch bump, no API change. |
| `aiosmtplib` | 3.0.2 | 5.1.2 | **The one genuinely exploitable finding**: `SMTP.mail()`/`.rcpt()` don't reject embedded CR/LF in caller-supplied addresses — and `EmailProvider.send_message` (`infrastructure/channels/providers/email.py`) builds its `To:` header directly from `message.metadata["customer_email"]`, which ultimately originates from customer-supplied data. A crafted customer email address could inject extra SMTP commands. Verified `aiosmtplib.send()`/`aiosmtplib.SMTP()` keyword signatures (`hostname`/`port`/`username`/`password`/`use_tls`) are unchanged across the 3→5 jump; full test suite green after the bump. |
| `black` | 24.10.0 | *(removed)* | Unused — `ruff format` (already this project's actual formatter since early on) is Black-compatible by design; `black` was dead weight left in `pyproject.toml`'s dev extras with no `.github/` workflow or pre-commit hook ever invoking it. Removing an unused dependency is a cleaner fix than patching a vulnerability in code that never runs. |

**Deferred, with justification** (not silently ignored):

- **`starlette` 0.41.3** (pinned transitively by `fastapi==0.115.6`) —
  several CVEs, but the fully-patched line requires Starlette 1.x, which
  in turn requires a FastAPI major-version jump (`fastapi` has since
  released up to 0.139.x while pinning newer Starlette ranges). A
  ~24-minor-version framework upgrade touching every one of this
  platform's 90+ endpoints is a dedicated upgrade project with its own
  regression-testing budget, not something to fold into a hardening
  pass alongside everything else in this milestone. **Tracked as the
  top-priority follow-up** — recommend a standalone milestone: bump
  `fastapi`/`starlette` together, re-run the full suite, and manually
  smoke-test WebSocket routes (`/ws/agent`, web-chat) and file-upload
  endpoints, since those are the areas most likely to have picked up
  breaking changes across this many releases.
- **`pytest` 8.3.4** — one CVE (predictable `/tmp/pytest-of-{user}`
  naming, a local multi-user race condition on Unix). Dev-only, never
  deployed to production, and the fix requires a pytest 9.x major bump
  whose compatibility with `pytest-asyncio`/`pytest-cov`/`pytest-env`
  wasn't verified in this pass — deferred rather than risking this
  build's entire 500+-test suite on an unverified major bump late in a
  long session. Low real-world severity for this project's threat model.
- **`ecdsa` 0.19.2** (transitive, via `python-jose[cryptography]`) — the
  Minerva timing-attack CVE has **no fix version at all** (the
  maintainers consider pure-Python constant-time ECDSA infeasible to
  guarantee and won't fix it). Confirmed not exploitable here: this
  platform only ever signs/verifies JWTs with `HS256`
  (`settings.jwt_algorithm` default and the only algorithm configured
  anywhere), never an ECDSA-based algorithm — the vulnerable
  `ecdsa.SigningKey.sign_digest()` code path is never invoked. Accepted
  as a risk with no current exposure; would need re-evaluation only if
  this platform ever added ES256/ES384 JWT support.

## Verification performed

11 new tests added (502 → 513 passing), all green under `pytest -q`,
`ruff check`/`ruff format --check`, and `mypy src`:

- `tests/unit/test_security_headers.py` (5 tests) — base headers present
  in both environments, CSP/HSTS absent in development, CSP/HSTS present
  in production, and the CORS wildcard-plus-credentials guard raising at
  startup vs. an explicit allowlist booting cleanly.
- `tests/integration/test_rate_limiting_endpoints.py` (6 tests) — real
  HTTP verification (not just the existing unit-level
  `FixedWindowRateLimiter` test) that `/auth/login`, `/auth/refresh`,
  `/auth/logout`, and `POST /csat/{id}/respond` all return 429 with a
  `Retry-After` header once exceeded, that every `/ai/*` endpoint is
  rate limited per authenticated user, and that one user's AI usage
  never throttles a different user's.

The full existing 502-test suite was re-run after every dependency bump
(python-jose, orjson, python-multipart, aiosmtplib) with zero
regressions. `docker-compose` files needed no changes — no new service,
no new runtime dependency requiring a rebuild beyond the existing
`backend`/`celery-*`/consumer images already rebuilt after each
milestone's dependency changes.

## Message redaction

Removing customer content on request, without destroying the record that
a message existed. See `docs/architecture/message-redaction.md`.

**Threat model.** The control exists for content that should never have
been stored: payment details typed into a chat, credentials, health
information volunteered in the wrong channel. The requirement is that
after redaction the content is not retrievable through any interface
this platform offers.

**What is guaranteed.** The body is overwritten in place, provider
metadata is filtered through an allow-list, attachments are deleted from
object storage, and every citation in Memory and Learning is removed.
Future analysis excludes the message at the source query. Verified by
tests that assert the string is absent from the API, the database row,
AI transcripts, search and the Conversation Inspector.

**What is not guaranteed, and must not be claimed to a customer:**

- **Backups taken before the redaction still contain it.** Restoring one
  restores the content. Erasure obligations that extend to backups need
  a documented backup-expiry period; this platform's sets are retained
  14 days locally and 30 remotely by default.
- **The customer's own copy is untouched.** A message delivered to
  WhatsApp, SMS or email cannot be recalled.
- **Postgres may retain the old row version** until the page is vacuumed
  and reused. The value is unreachable through SQL but is not
  cryptographically erased from disk.

**Separation of duties.** `messages.redact` is held by Administrators
and the Owner, never Agents. It is deliberately separate from
`conversations.delete`, which remains Owner-only and additionally gates
bulk destruction through agent removal — adding a new destructive
permission is the natural way to widen an old boundary by accident, so
`test_destructive_permission_boundaries.py` asserts it did not.

**Audit.** `message_redactions` is append-only: no code path updates or
deletes a row, and its foreign keys are `SET NULL` so the record outlives
what it describes. It holds actor, timestamp, reason, message,
conversation, company, and counts of what was purged — and never the
content itself.

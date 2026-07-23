# OWASP ASVS Checklist (Level 2 baseline)

A working checklist against OWASP's Application Security Verification
Standard, scoped to what's realistic to verify for this codebase today.
Each item names the control, whether it's implemented, and where.
Re-run this checklist whenever a new milestone touches auth, data
handling, or external integrations. See `docs/security/hardening.md` for
the audit narrative behind these entries and `docs/security/pentest-checklist.md`
for manual verification steps.

## V1 — Architecture, Design and Threat Modeling

- [x] Every entity is scoped to a `company_id` (multi-tenancy boundary)
  — enforced at the repository layer on every query, not just the API
  layer (`infrastructure/repositories/*.py`).
- [x] Clean Architecture layering (domain → application → infrastructure
  → api) keeps business rules independent of the web framework and ORM.
- [x] Public, unauthenticated endpoints (webhooks, CSAT respond, web-chat
  sessions) are enumerated and each has its own documented trust model —
  see `docs/architecture/channels.md`, `docs/architecture/reports-analytics.md`,
  `docs/architecture/web-chat.md`.

## V2 — Authentication

- [x] Passwords hashed with bcrypt via passlib (`core/security.py`).
- [x] JWT access/refresh tokens, explicit algorithm allowlist on decode
  (no `alg: none`/confusion risk).
- [x] Refresh tokens are individually trackable/revocable (`jti` claim +
  `RefreshTokenStore`).
- [x] Login, register, refresh, and logout are all rate limited
  (`core/rate_limit.py`, see `docs/security/hardening.md`).
- [ ] Multi-factor authentication — not implemented; no MFA requirement
  named in the product spec so far. Flag for a future milestone if
  enterprise/financial/healthcare customers require it (CLAUDE.md names
  those as target customer segments).
- [x] Password strength validated at registration
  (`api/schemas/validators.py::validate_password_strength`).

## V3 — Session Management

- [x] Stateless bearer-JWT sessions — no server-side session store to
  leak, no cookies, so session-fixation/CSRF classes don't apply the way
  they would to cookie-based auth.
- [x] Access tokens short-lived (`access_token_expire_minutes`, default
  15 min); refresh tokens longer-lived but individually revocable.
- [x] Logout invalidates the specific refresh token used
  (`AuthService.logout`), not a blanket "log out everywhere."

## V4 — Access Control

- [x] RBAC enforced via `require_permission(code)` on every
  permission-gated route — fails fast at import time on an unknown
  permission code (`api/deps.py`).
- [x] Every permission check is scoped to `auth.company_id` — no
  endpoint trusts a client-supplied company id for authorization
  decisions.
- [x] Public endpoints that bypass RBAC (webhooks, CSAT respond) are
  authorized by a different mechanism (signature/shared secret, signed
  token) — documented per-endpoint, not an oversight.

## V5 — Validation, Sanitization and Encoding

- [x] Every request body validated by a Pydantic schema at the API
  boundary (`api/schemas/*.py`) — `Field` constraints
  (`min_length`/`max_length`/`ge`/`le`), `EmailStr` where applicable.
- [x] No raw SQL string interpolation anywhere — SQLAlchemy Core/ORM
  parameterized queries exclusively (verified via full-codebase grep,
  see `docs/security/hardening.md`).
- [x] No HTML rendering anywhere in this backend — XSS is a frontend
  concern, out of scope for this API.
- [ ] Rich-text/HTML sanitization for user-generated content (internal
  notes, quick replies, knowledge base articles) — not currently
  applicable since none of these are rendered as HTML by this backend;
  revisit if a future frontend renders any of this content as raw HTML
  rather than as plain text/Markdown-escaped.

## V6 — Stored Cryptography

- [x] `ChannelConfig`/`ErpConfig` credentials encrypted at rest
  (`infrastructure/security/crypto.py`, AES-256-GCM, fresh nonce per
  encryption).
- [x] Encryption key (`credentials_encryption_key`) is a required
  setting, `min_length=32`, no default — separate from `jwt_secret_key`
  so rotating one never invalidates the other.
- [ ] Key rotation procedure — not yet documented/automated. A real gap
  for production operations; flag for `docs/deployment/` when that
  directory is built out (M29).

## V7 — Error Handling and Logging

- [x] Centralized exception→HTTP-status mapping
  (`core/exceptions.py::_STATUS_MAP`) — no endpoint hand-rolls error
  responses, so no endpoint can accidentally leak a stack trace.
- [x] Structured logging (`structlog`) throughout — no `print()`
  debugging left in `src/` (spot-checked).
- [x] `/docs`/`/redoc` (which could leak API shape to an unauthenticated
  scanner) disabled in production (`main.py`).

## V8 — Data Protection

- [x] Every credential-bearing API response (`ChannelConfigResponse`,
  `ErpConfigResponse`) explicitly excludes `credentials`/`webhook_secret`
  — write-only over the API, confirmed by Pydantic response models that
  simply don't declare those fields.
- [x] Security response headers (`X-Content-Type-Options`,
  `X-Frame-Options`, CSP in production, HSTS in production) — see
  `docs/security/hardening.md`.

## V9 — Communications

- [x] TLS termination is nginx's responsibility (infra layer, outside
  this backend) — HSTS header instructs browsers to enforce it once
  configured.
- [ ] Certificate/TLS configuration itself — not yet reviewed as part of
  this milestone (nginx config lives under `docker/nginx/`); flag for
  M27 (Observability & DevOps) or a dedicated infra review.

## V10 — Malicious Code

- [x] Dependency vulnerability scan performed this milestone
  (`pip-audit`) — see `docs/security/hardening.md` for full results and
  remediation.
- [ ] Automated dependency scanning in CI — no `.github/` workflows
  exist yet in this repository (flag for M27).

## V11 — Business Logic

- [x] Conversation status transitions are validated against an explicit
  allowed-transitions map, not accepted unconditionally
  (`ConversationService._ALLOWED_TRANSITIONS`).
- [x] CSAT responses are one-per-conversation (unique constraint), not
  re-submittable.

## V12 — Files and Resources

- [x] Attachment uploads validated for content-type/size before storage
  (`application/services/attachment_validation.py`).
- [x] MinIO object storage keys are generated server-side
  (`f"{conversation_id}/{uuid4()}/{filename}"`), never a raw
  client-supplied path — no path traversal surface.

## V13 — API and Web Service

- [x] Every endpoint requires authentication except the explicitly
  documented public ones (webhooks, CSAT respond, web-chat session
  creation, health check) — no accidental unauthenticated route.
- [x] CORS configured with an explicit origin allowlist, guarded against
  a wildcard+credentials misconfiguration (`main.py`, new this
  milestone).

## V14 — Configuration

- [x] All secrets sourced from environment variables
  (`core/config.py::Settings`, `pydantic-settings`), no hardcoded
  secrets anywhere in `src/`.
- [x] Debug/docs endpoints disabled in production.
- [x] Every setting with security implications (rate limits, token
  lifetimes, encryption key) is centralized in one `Settings` class, not
  scattered across the codebase.

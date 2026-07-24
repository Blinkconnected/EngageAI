# Go-Live Checklist

A concrete pre-launch checklist reflecting this platform's *actual*
current state — not a generic template. Items marked done (`[x]`) were
verified during this build; items marked open (`[ ]`) are real gaps that
must be closed (or explicitly, knowingly accepted as risk by whoever
owns the launch decision) before handling real customer data, especially
for the Healthcare/Financial/Government/Enterprise segments CLAUDE.md
names as target customers — those segments carry compliance obligations
this checklist does not itself satisfy on its own.

## Security

- [x] OWASP ASVS review performed — `docs/security/owasp-asvs-checklist.md`
- [x] No SQL injection surface (parameterized queries throughout, verified)
- [x] No XSS surface (pure JSON API)
- [x] No CSRF surface (bearer-JWT-only, zero cookies)
- [x] Password hashing (bcrypt), JWT algorithm-confusion protection
- [x] Rate limiting on auth endpoints, public endpoints, and AI usage
- [x] Security response headers + CORS misconfiguration guard
- [x] Dependency vulnerability scan performed and triaged — `docs/security/hardening.md`
- [ ] **`starlette`/`fastapi` major-version upgrade** — deferred with
      justification (see `docs/security/hardening.md`), but should be
      scheduled as its own project before launch if the CVEs it carries
      are unacceptable for your risk posture.
- [ ] **TLS/HTTPS** — not configured. Deploy behind a TLS-terminating
      load balancer, or add a `listen 443 ssl` block + certificates to
      `docker/nginx/nginx.prod.conf`. **Do not launch without this.** This
      is not theoretical: M36's production-stack verification confirmed
      *live* unsolicited traffic (real external IPs, Bing crawler ranges)
      already reaching this environment's port 80 in plain HTTP — see
      `docs/ROADMAP.md`'s M36 entry.
- [ ] **Secrets manager integration** — currently a plain `.env` file.
      Acceptable for a single-operator early launch; migrate to a real
      secrets manager (Vault, AWS Secrets Manager, etc.) before scaling
      the operations team or handling regulated data.
- [ ] **This environment's `.env` still has 7 literal `change-me-...`
      placeholder secrets** (`POSTGRES_PASSWORD`, `DATABASE_URL`,
      `RABBITMQ_DEFAULT_PASS`, `RABBITMQ_URL`, `MINIO_ROOT_PASSWORD`,
      `S3_SECRET_KEY`, `GF_SECURITY_ADMIN_PASSWORD`) — confirmed via
      direct inspection during M36. Harmless for this sandbox but a
      concrete blocker for any real deployment. **Rotating
      `POSTGRES_PASSWORD` on an already-initialized cluster needs an
      in-database `ALTER USER` alongside the `.env` edit** — a
      coordinated rotation, not a find-and-replace; plan it as its own
      step before launch.
- [ ] **Penetration test** — `docs/security/pentest-checklist.md` is a
      checklist for a human tester to execute against a real running
      instance; it has not itself been executed end-to-end by a
      dedicated tester as part of this build.

## Data & backups

- [x] Automated Postgres backups + a verified restore drill —
      `scripts/backup_postgres.sh`/`verify_backup_restore.sh`
- [x] Disaster recovery plan — `docs/deployment/disaster-recovery.md`
- [ ] **Off-host backup shipping** — backups currently land in
      `backups/` on the same host as the database. A full host loss
      today loses the backups along with everything else. **Wire backup
      upload to off-host storage before launch.**
- [ ] **MinIO/attachment backup** — no automated backup exists for
      uploaded attachments (a real, documented gap — see
      `docs/deployment/disaster-recovery.md`). Matters most for
      compliance-sensitive customers who may need to retain/produce
      customer-uploaded files.
- [ ] **Encryption key rotation drill** — `docs/deployment/runbooks.md`
      documents the *procedure* but it has not been executed as a live
      drill against this specific deployment.

## Observability

- [x] Prometheus metrics (backend, Postgres, Redis, RabbitMQ, Celery)
- [x] Grafana dashboards (5) + alerting rules (6), provisioned and
      verified loaded
- [x] Structured JSON logging → Loki, with level-based labels
- [x] Dependency-aware readiness probe (`/health/ready`)
- [ ] **Real alert notification destination** — the contact point is a
      deliberate placeholder webhook (`docker/grafana/provisioning/
      alerting/contact-points.yml`). **Wire in a real Slack/PagerDuty/
      email destination before launch** — alerts that fire into a void
      are worse than no alerting, since they create false confidence.
- [ ] **On-call rotation / paging policy** — an organizational decision
      outside this codebase's scope; needs to exist before alerting is
      meaningful.

## Performance & scale

- [x] Load test methodology + tooling — `scripts/load_test.py`
- [x] Query optimization pass — two composite indexes added and verified
- [ ] **Load test against production-class hardware** — this build's own
      load test ran against a 2-CPU-core sandbox shared with the entire
      stack; the absolute numbers are not production-representative
      (see `docs/architecture/performance.md`). **Re-run before launch
      against real target hardware/instance sizing.**
- [ ] **`messages` table partitioning** — a documented playbook exists
      (`docs/architecture/performance.md`) but is intentionally not
      applied; fine at launch (near-zero data), revisit per the
      documented trigger conditions as real volume accumulates.

## CI/CD & deployment

- [x] `.github/workflows/ci.yml` — lint, test, build, scan on every push/PR
- [ ] **Real deploy target** — the `deploy` job is an intentional,
      documented placeholder (no fabricated target). **Configure real
      deploy credentials/target before relying on this pipeline for
      production releases.**
- [x] Migrations apply automatically and idempotently on container start
      — genuinely verified during M36 (not just assumed): a from-scratch
      run against an empty database originally failed with a duplicate-
      key error (six early "seed permissions" migrations collided with
      the first migration's live-catalog import), fixed and re-verified
      clean. See `docs/ROADMAP.md`'s M36 entry.
- [x] Docker Compose prod overlay (lean runtime images, resource limits,
      no bind mounts) — brought up for real during M36, not just built;
      found and fixed 3 more real bugs (Celery/consumer containers
      permanently false-"unhealthy", nginx's own healthcheck always
      failing on an IPv6/IPv4 `localhost` mismatch, and a production
      `npm run build` failure M35's own verification had missed).

## Frontend

- [x] **Golden-path frontend shipped (M30-M36)**: Authentication,
      Dashboard, Company Management, Agents, Channels (incl. WhatsApp
      connect), Inbox/Conversation View/Reply/Realtime, Customers/
      Timeline/ERPNext View, and Reports (Executive/Conversations/Agent
      Performance/Queues/SLA/CSAT/AI Usage/My Performance, with PDF/Excel
      export) — all verified end to end against the real production
      build in M36, not just dev-mode/mocked.
- [ ] **Several CLAUDE.md-listed features still have no frontend**:
      Departments, Teams, Queues, Routing Rules, Workflows, Knowledge
      Base, Quick Replies management UIs, and an Audit Logs viewer (the
      backend/API for all of these is complete — `GET /audit-logs`
      included PDF/Excel export and was exercised directly via API during
      M36's smoke test, just with no dedicated page yet). Scoped to M37.
      No longer "the single largest gap" now that the golden path exists,
      but still a real gap for a literal, feature-complete go-live.

## Legal & compliance (organizational, not code)

- [ ] Data processing agreements / privacy policy in place, matching
      actual data handling (this codebase's audit logging, soft-delete,
      and encryption-at-rest choices support compliance work but don't
      constitute it on their own).
- [ ] For Healthcare customers specifically: HIPAA obligations (BAAs,
      access controls beyond RBAC, audit log retention policy) —
      RBAC/audit logging exist; a formal compliance review has not been
      performed as part of this build.
- [ ] For Financial customers: relevant regulatory review (varies by
      jurisdiction) — not performed as part of this build.

## Final sign-off

This checklist should be reviewed and explicitly signed off (who
reviewed, what was accepted as a known risk vs. fixed, and when) before
the first real customer's data enters the system — not just checked off
silently.

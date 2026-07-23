# Disaster Recovery Plan

Failure scenarios, recovery procedures, and the RTO/RPO targets this
platform's current (single-host Docker Compose) architecture can
realistically meet. Re-evaluate every target here once the platform
moves beyond a single host — see `docs/architecture/observability.md`'s
note on nginx load balancing and horizontal scaling for what's already
in place versus what a real multi-node deployment would still need.

## RTO/RPO targets (single-host deployment)

| Metric | Target | Basis |
|---|---|---|
| RPO (data loss window) | ≤ 24 hours | Daily `scripts/backup_postgres.sh` — reduce by scheduling it more frequently if the business need warrants it; nothing in the script itself limits the interval |
| RTO (time to restore service) | ≤ 1 hour | Re-provisioning a host + `docker compose up` + `scripts/restore_postgres.sh` against a recent backup, assuming host-level infrastructure (DNS, load balancer, TLS termination) is already in place |

These targets assume a **single-host** deployment with no standby
replica — a real disaster (host loss) means provisioning a *new* host
before any of the recovery steps below can even start. If sub-hour RTO
against total host loss is a real business requirement, the necessary
next step is a warm/hot standby (a second host with the stack
pre-provisioned, replicating from backups or Postgres streaming
replication) — not built today, since no specific customer commitment
has required it yet.

## Scenario: PostgreSQL data loss or corruption

**Detection**: `/health/ready` reports `"database": "unreachable"`; the
Grafana "PostgreSQL is down" alert fires; or queries return corrupted/
unexpected data.

**Recovery**:
1. Stop write traffic if the database is still reachable but suspected
   corrupted: `docker compose stop backend celery-worker celery-beat`
   plus every consumer, to prevent further writes against bad data.
2. Identify the most recent trustworthy backup in `backups/` (verify it
   first with `scripts/verify_backup_restore.sh <file>` against a
   scratch database if there's any doubt about which one is clean).
3. `docker compose stop postgres`, then either restore into the existing
   volume or recreate it from scratch, then
   `docker compose up -d postgres` and wait for it to report healthy.
4. `./scripts/restore_postgres.sh <backup-file> --force` (or with the
   interactive confirmation, restoring into the real `POSTGRES_DB`).
5. `docker compose up -d backend celery-worker celery-beat` + every
   consumer — migrations re-apply automatically and are idempotent.
6. Confirm via `/health/ready` and a manual smoke test (login, list a
   few resources) before declaring recovery complete.

**Data loss window**: everything written since the restored backup was
taken — this is exactly the RPO gap the backup schedule determines.

## Scenario: RabbitMQ data loss

Durable queues persist to disk (`rabbitmq_data` volume) — a container
restart alone loses nothing. If the **volume itself** is lost:

1. In-flight domain events not yet relayed/consumed are lost — the
   transactional outbox (`event_outbox` table, in Postgres, backed up
   separately) still has every event that was ever published, with
   `dispatched_at` tracking what already made it to the broker. Anything
   with `dispatched_at IS NULL` at the time of loss needs to be
   re-relayed once RabbitMQ is back — the outbox relay's own
   `SELECT ... FOR UPDATE SKIP LOCKED` claim query already handles this
   correctly on its next scheduled run with zero manual intervention,
   since it only ever looks at `dispatched_at IS NULL` rows.
2. `docker compose up -d rabbitmq` (a fresh volume is fine — durable
   queues/exchanges are redeclared by every consumer/the relay on
   connect, per `infrastructure/events/rabbitmq.py`).
3. Anything with `dispatched_at` already set but not yet *consumed*
   before the loss (acknowledged by a specific consumer) is genuinely
   lost — e.g. a notification that was relayed but never wrote its
   `Notification` row. No automated replay exists for this narrower
   window; it's a small, accepted gap (seconds-to-minutes of exposure
   in practice, given the relay runs every 5 seconds) rather than
   something requiring event-sourcing-style replay infrastructure.

## Scenario: Redis data loss

Redis here is used for refresh tokens, web-chat sessions, rate-limit
counters, and ephemeral pub/sub — nothing in `Notification`/business
data lives only in Redis. Losing it means:

- Every user is forced to log in again (refresh tokens gone).
- Every active web-chat session is invalidated (a customer's widget
  session ends; they'd start a new one).
- Rate limit counters reset (briefly more permissive, not a security
  hole — just a transient window).

No backup/restore needed for Redis — `docker compose up -d redis`
(fresh volume) and let the application layer re-establish state
naturally through normal use.

## Scenario: MinIO (attachment storage) data loss

Attachments (message attachments, uploaded files) live only in MinIO —
there is currently **no automated backup for MinIO**, only Postgres.
This is a real gap: `message_attachments` rows would reference storage
keys that no longer resolve to real objects. Until MinIO backup is
built, mitigate via the underlying object storage's own durability
(e.g. if backed by real S3 in production rather than the bundled MinIO
container, rely on S3's own durability guarantees and versioning rather
than an application-level backup). **Action item for the next
infrastructure milestone**: either enable MinIO bucket replication to a
second location, or move to a managed object store with built-in
durability guarantees before handling attachments that matter for
compliance (healthcare/financial customers, per CLAUDE.md's target
segments, will very likely require this).

## Scenario: Full host loss

1. Provision a new host with Docker + Compose (see
   `docs/deployment/production.md`'s bring-up steps).
2. Restore `.env` from the organization's secrets manager/vault (never
   from a plaintext copy in the lost host's disk image — see
   `docs/security/hardening.md` for why secrets never live in version
   control).
3. `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build`
4. Follow the PostgreSQL recovery scenario above against the most recent
   off-host backup — this is why `backups/` must be shipped somewhere
   *other than the host itself* (object storage, a separate backup
   host) to survive a full host loss; a backup that only lives on the
   same disk as the database it protects isn't a real disaster-recovery
   backup. **Action item**: wire `scripts/backup_postgres.sh` to also
   push each backup to off-host storage before this plan can claim to
   survive a full host loss in practice.

## After any recovery

Always run `scripts/verify_backup_restore.sh` against the freshly
restored database and a full manual smoke test (register/login,
create/list a resource in 2-3 feature areas, check `/health/ready`)
before declaring the incident resolved. Write up what happened — this
plan should be updated with anything it didn't anticipate.

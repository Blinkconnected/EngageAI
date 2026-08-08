# Disaster Recovery Plan

Failure scenarios, recovery procedures, and the RTO/RPO targets this
platform's current (single-host Docker Compose) architecture can
realistically meet. Re-evaluate every target here once the platform
moves beyond a single host — see `docs/architecture/observability.md`'s
note on nginx load balancing and horizontal scaling for what's already
in place versus what a real multi-node deployment would still need.

## RTO/RPO (single-host deployment)

These were targets. They are now **measured** — `scripts/dr_rehearsal.sh`
restores all four asset classes and times every phase, and the numbers
below come from an executed run rather than an estimate.

| Metric | Value | Basis |
|---|---|---|
| RPO (data loss window) | ≤ 24 hours | Nightly `blinkengage-backup.timer` at 02:30 UTC. Anything written after the last successful backup is lost. |
| RTO — restore phase | **4.8 s measured** | Rehearsal, 2026-08-05, against a 1.5 MB dump and 4.3 MB of objects. |
| RTO — realistic full outage | 30–60 min | The measured figure is the restore *only*; see below. |

### The measured number is not the length of the outage

The rehearsal reported 4.8 s. That is a true measurement of one phase, on
the current dataset, on a host that was already running. It excludes
everything that dominates a real recovery:

| Phase | Measured | Real outage |
|---|---|---|
| Detecting the failure | — | 0–15 min (alerting is verified — see below) |
| Deciding to fail over | — | 5–20 min (human) |
| Provisioning a replacement host | — | 10–30 min, if the host is gone |
| Fetching the set from off-host | — | minutes to hours, on set size and link |
| **Restore (measured)** | **4.8 s** | scales with data |
| Starting containers, migrations | — | 3–8 min |
| DNS / TLS cutover | — | 1–30 min, on TTL |

**Plan for 30–60 minutes.** Quote the measured figure only for what it
measures.

The dataset at rehearsal time was small: 98 tables, 35 companies, 29
objects. The database restore is `psql` replaying a plain dump and the
object restore is a `tar` extract — both roughly linear in size. At 10 GB
of attachments expect the restore phase in tens of minutes, dominated by
transfer from off-host rather than by either restore. **Re-run the
rehearsal after significant growth**; that is the only thing that keeps
this table true.

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

Attachments live in MinIO, and they are now backed up: every nightly set
contains `minio.tar.gz`, an archive of the MinIO data volume including
bucket metadata and policies.

**Recovery**:
1. `docker compose up -d minio && docker compose stop minio`
2. Extract the archive over the volume:
   ```bash
   docker run --rm \
     -v blinkengage_minio_data:/data \
     -v "$PWD/backups/<TIMESTAMP>:/backup:ro" \
     --entrypoint sh postgres:17-alpine \
     -c 'rm -rf /data/* && tar -C /data -xzf /backup/minio.tar.gz'
   ```
3. `docker compose start minio`

**Restore objects from the same set as the database.** A database
restored beside a mismatched object store looks healthy and serves broken
attachment links — which is harder to notice than an outage. The
rehearsal checks this pairing by starting a real MinIO server against the
restored volume and listing objects through the S3 API: extracting an
archive proves the bytes survived, but only serving them proves the
bucket metadata did.

Volume-level rather than `mc mirror`, because the MinIO image is minimal
(no `tar`, no `sed`) and a host-side client would have to be kept in step
with the server version.

Still worth doing before compliance-sensitive workloads (healthcare,
financial): bucket replication to a second location, or a managed object
store with its own durability guarantees. Nightly archives bound the loss
to 24 hours; they do not make the object store itself redundant.

## Scenario: Full host loss

1. Provision a new host with Docker + Compose (see
   `docs/deployment/production.md`'s bring-up steps).
2. **Restore the source.** Every later step needs it — step 4 builds
   images from it, and the checkout in step 6 has nothing to check out
   without it. `source.bundle` in the backup set is a single file
   containing the whole repository, every branch and tag:
   ```bash
   git clone backups/<TIMESTAMP>/source.bundle blinkengage
   cd blinkengage
   ```
   A bundle clones exactly like a remote. Verify it before relying on
   it — `git bundle verify backups/<TIMESTAMP>/source.bundle` — though
   `backup_all.sh` already verified it at creation time and refuses to
   ship one that fails.

   > This step was missing until 2026-08-08, and its absence made this
   > scenario unexecutable: the runbook told you to `git checkout` a
   > commit on a host that had no repository, and to `--build` images
   > from source that no longer existed anywhere. The repository has no
   > remote, so the bundle is not a convenience — it is the only copy.

3. Restore `.env`, either from the organization's secrets manager or
   from the encrypted `secrets.tar.gz.gpg` in the backup set:
   ```bash
   gpg --decrypt backups/<TIMESTAMP>/secrets.tar.gz.gpg | tar -xz
   chmod 600 .env
   ```
   The archive is AES-256 symmetric-encrypted with `BACKUP_PASSPHRASE`.
   **That passphrase must not live only on the platform host** — if it is
   lost with the host, every backed-up credential is unrecoverable. Store
   it in the organisation's password manager before go-live. See
   `docs/security/hardening.md` for why secrets never live in version
   control.
4. `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build`
5. Fetch the most recent set from off-host and verify it before
   trusting it:
   ```bash
   rsync -az backup@backups.internal:/srv/blinkengage/<TIMESTAMP> ./backups/
   cd backups/<TIMESTAMP> && sed -n '/^---$/,$p' MANIFEST | tail -n +2 | sha256sum --check
   ```
   A checksum failure means fetch an older set — restoring a corrupt
   archive spends the outage and then fails.
6. Check out the commit the set was taken at. The dump carries a schema
   at a specific Alembic head, and application code newer than that
   schema fails on its first write:
   ```bash
   git checkout $(grep '^git_commit=' backups/<TIMESTAMP>/MANIFEST | cut -d= -f2)
   ```
7. Restore configuration, secrets, database and objects from that set,
   then follow the PostgreSQL and MinIO scenarios above.

`scripts/backup_all.sh` pushes each set off-host via rsync when
`BACKUP_REMOTE` is set, and says so loudly in its output when it is not —
a backup that only lives on the same disk as the database it protects
does not survive the failure it exists for.

## Rehearsing this plan

A recovery plan nobody has executed is a document, not a capability. The
first restore of a backup should never be the one performed during an
outage.

```bash
BACKUP_PASSPHRASE=<passphrase> ./scripts/dr_rehearsal.sh
```

Non-destructive by construction: the database restores into
`blinkengage_dr_rehearsal`, objects into a throwaway Docker volume served
by a temporary MinIO container, config and secrets into a temp directory.
Production is read from and never written to; everything is torn down at
the end unless `--keep` is passed.

Two cadences, because they answer different questions:

| Drill | Cadence | Answers |
|---|---|---|
| `scripts/verify_backup_restore.sh` | weekly, `blinkengage-restore-drill.timer` | does last night's dump restore? |
| `scripts/dr_rehearsal.sh` | quarterly, and after any change to the backup or restore path | does the *whole platform* come back, and how fast? |

### Rehearsal result — 2026-08-05

```
Phase 0 — backup integrity
  PASS  MANIFEST present
  PASS  every artefact matches its recorded checksum
Phase 1 — database
  PASS  database restored into blinkengage_dr_rehearsal
  PASS  98 tables present
  PASS  schema at migration f6c3d95a2e81
  PASS  business data present (35 companies)
Phase 2 — object storage
  PASS  object archive extracted
  PASS  MinIO started against the restored volume
  PASS  29 object(s) readable through the S3 API
Phase 3 — configuration
  PASS  configuration archive extracted
  PASS  every file needed to rebuild the stack is present
Phase 4 — secrets
  PASS  secrets archive decrypted
  PASS  .env recovered with 30 variables

0. Integrity check                    0.0s
1. Database restore                   2.5s
2. Object storage restore             2.0s
3. Configuration restore              0.0s
4. Secrets restore                    0.1s
TOTAL (measured RTO)                  4.8s

REHEARSAL PASSED — all four asset classes restored and verified.
```

## Remaining gaps

Recorded rather than hidden. Each is a decision, not an oversight.

**RPO is 24 hours.** Nightly dumps mean up to a day of conversations,
messages and attachments are lost in a total-loss scenario. Closing it
needs WAL archiving or streaming replication — a change to the database
deployment, not a script. Acceptable for the pilot; revisit before the
platform carries production volume for paying customers.

**Restore is manual.** A person reads this file and runs the steps. That
is deliberate at this maturity: an automated restore that fires on a
false positive is a worse failure than a slow manual one.

**Single host, no standby.** Recovery means provisioning a new host,
which is the bulk of the realistic RTO.

**The repository has no remote.** `git remote -v` is empty; 194 commits
exist on this host and inside `source.bundle` in each backup set, and
nowhere else. The bundle makes the code survivable *provided the set
reaches off-host storage* — which means `BACKUP_REMOTE` must be set. It
also means CI has never run, since `.github/workflows/ci.yml` triggers
on push to `main` and nothing has ever been pushed. Adding a remote
closes both at once and is the single highest-value action available
here.

**The rehearsal ran against a small dataset.** The measured restore time
does not extrapolate to production volume; re-run it as data grows.

## After any recovery

Always run `scripts/verify_backup_restore.sh` against the freshly
restored database and a full manual smoke test (register/login,
create/list a resource in 2-3 feature areas, check `/health/ready`)
before declaring the incident resolved.

Confirm attachments load in the UI — that is the one check proving the
database and object storage came from the *same* set.

Run `./scripts/verify_alerting.sh` too: a platform whose monitoring did
not come back is not recovered, it is only serving traffic.

Record the actual RPO (now, minus `created_utc` in the manifest) and the
actual RTO. Write up what happened, and **update this plan** with
anything it did not anticipate — a runbook that was wrong during an
incident and not corrected afterwards will be wrong during the next one.

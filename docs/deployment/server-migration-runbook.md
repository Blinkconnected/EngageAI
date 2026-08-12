# Server Migration Runbook — moving the platform to new hardware

Moving BlinkEngage from `ubuntu-4gb-nbg1-1` to a new host, keeping every
piece of state, and changing exactly one thing the outside world can see:
the IP address behind `engage.blinkconnected.com`.

This is not the disaster-recovery plan. `docs/deployment/disaster-recovery.md`
answers "the host is gone, what do we do" — it optimises for recovering
from whatever survived. This document answers "the host is fine and we are
leaving it", which is a much better position: both hosts exist at once,
nothing is under time pressure, and the new host can be proven correct
before a single user reaches it.

## What is actually changing

**The IP address, and nothing else the outside world can see.** The
outgoing host's address appears nowhere in this repository — grep for it
before you start and confirm that stays true. Everything reaches the
platform through the domain:

```
engage.blinkconnected.com  →  A record  →  <the host's IP>
```

So the cutover is a DNS change. The certificate follows the domain and
keeps working; `PUBLIC_BASE_URL`, `CORS_ALLOW_ORIGINS` and the frontend's
API base are all domain- or path-relative and need no edit.

Three things are tied to the address and must be handled:

| Tied to the IP | What to do |
|---|---|
| DNS `A` record | Repoint at cutover. Lower the TTL 24h beforehand. |
| SSH access | New host's own key/`authorized_keys`. |
| Anything allow-listing the old IP | **Check your upstreams** — see below. |

That last row is the one that bites. The platform's own config has no IP
in it, but *other people's* config might have this host's address in an
allow-list: payment providers, ERP endpoints, WhatsApp/Meta webhook
sources, SMTP relays, or a customer's firewall. Grep the channel
connector credentials and ask each provider before cutover, because this
is the failure that appears hours later as "messages stopped arriving"
rather than at cutover as an outage.

## Read this first: the live site runs the dev stack

`docker inspect` on the running edge reports
`com.docker.compose.project.config_files=/root/BlinkEngage/docker-compose.yml`
— the base file alone. The production overlay has never been cut over
(see `edge-cutover-runbook.md`, whose 2026-08-11 attempt took the site
down for about three minutes and was reverted).

Concretely, today's production site is:

- stock `nginx:1.27-alpine` proxying the **Vite dev server**, not the
  built bundle served by `blinkengage-nginx:prod`
- `ENVIRONMENT=development`, `DEBUG=true`
- backend, Grafana and Prometheus published on `0.0.0.0`

**This migration is the safe moment to fix that**, and it is the reason
to prefer it over a straight disk clone. The edge cutover was dangerous
before because ports 80 and 443 can only be held by one container, so the
swap had to happen on the live host. On a new host there is no live
traffic to protect: bring up the prod overlay, prove it completely, and
only then move DNS. The risk the cutover runbook was written around
disappears.

If you would rather change one thing at a time, that is a legitimate
call — run the new host on the dev stack first, cut DNS over, then do the
edge cutover separately a week later. It is slower and it carries
`DEBUG=true` into the new host for that week. Decide deliberately; do not
arrive at it by accident.

## What moves

| Asset | Carried by | Size |
|---|---|---|
| Source | git remote, plus `source.bundle` in the set | — |
| **`.env`** | `env.original` in the export (0600) | 1.9 KB |
| Database | `database.sql.gz` (primary), volume archive (fallback) | 182 MB |
| Attachments | `blinkengage_minio_data` | 528 KB |
| Durable queues | `blinkengage_rabbitmq_data` | 14 MB |
| Metrics history | `blinkengage_prometheus_data` | 786 MB |
| Grafana users, dashboards, annotations | `blinkengage_grafana_data` | 89 MB |
| Log history | `blinkengage_loki_data` | 81 MB |
| TLS material | `letsencrypt.tar.gz` | small |

**`scripts/backup_all.sh` alone is not enough for a migration.** It
carries the four asset classes needed to rebuild the *product* — database,
objects, config, secrets, source. It does not carry Prometheus, Grafana,
Loki or RabbitMQ, because a backup set is not trying to preserve a
deployment's history. `scripts/migrate_export.sh` wraps it and adds them.

Deliberately **not** moved:

- **`redis_data`** — ephemeral by design (refresh tokens, chat sessions,
  rate-limit counters). The AOF on the old host is corrupt anyway
  (`Bad file format reading the append only file`), which is why the
  container is in a restart loop today. A fresh volume costs every user
  one re-login and fixes the corruption for free.
- **`frontend_node_modules`** — 542 MB of build cache, rebuilt on arrival.
- **Docker images** — rebuilt from source, so the new host runs what the
  repository says rather than what the old host drifted to.

## Before the window

Nothing here touches the running platform.

**1. Lower the DNS TTL.** 24 hours ahead, set the A record's TTL to 300s.
This is the single largest lever on cutover length: at a 3600s TTL some
resolvers keep sending users to the old host for an hour.

**2. Get the code off this host.** 12 commits on `feat/mobile-readiness`
are unpushed, and there are uncommitted working-tree changes. The export
captures uncommitted work as `uncommitted.patch`, but the durable fix is
to push.

```bash
cd /root/BlinkEngage
git push origin feat/mobile-readiness
```

**3. Provision the new host.** Ubuntu, Docker + Compose v2, and **more
than 38 GB of disk** — the old host is at 85% with images, build cache and
volumes. 80 GB is a reasonable floor.

**4. Free space on the old host** so the export has somewhere to go:

```bash
docker builder prune -f      # ~3.4 GB of build cache on this host
```

**5. Check upstream IP allow-lists** (see above). This is the long-lead
item — providers can take days to update an allow-list.

**6. Warm pass.** Moves the bulk while everything is still running, so the
window only has to carry the delta:

```bash
./scripts/migrate_export.sh --warm
rsync -azP /var/tmp/blinkengage-migration/warm/ \
  root@NEW_HOST:/var/tmp/blinkengage-migration/warm/
```

A warm export is **not** consistent and must not be cut over to. Its job
is to make the cold rsync small, and to let you rehearse
`migrate_import.sh --no-start` on the new host before the window.

## The window

Expect 30–60 minutes, matching `disaster-recovery.md`'s realistic RTO.

**1. Stop the writers and export.** Downtime starts here.

```bash
cd /root/BlinkEngage
./scripts/migrate_export.sh --cold
```

The script stops the writers, takes the backup set, then stops the
stateful services before archiving their volumes — Grafana's SQLite and
Prometheus's TSDB cannot be tarred safely while running. It restarts the
stack on exit; if you are proceeding, stop it again:

```bash
docker compose stop
```

Two hosts serving the same domain and both accepting writes is how a
migration becomes two divergent databases with no way to merge them.

**2. Transfer.**

```bash
rsync -azP /var/tmp/blinkengage-migration/cold/ \
  root@NEW_HOST:/var/tmp/blinkengage-migration/cold/
```

**3. Import, on the new host.**

```bash
git clone git@github.com:Blinkconnected/EngageAI.git BlinkEngage
cd BlinkEngage
git checkout $(grep '^git_commit=' /var/tmp/blinkengage-migration/cold/MANIFEST | cut -d= -f2)
./scripts/migrate_import.sh --export /var/tmp/blinkengage-migration/cold
```

The import verifies checksums before trusting anything, refuses to run if
the checkout does not match the export's commit, restores `.env` and sets
`ENVIRONMENT=production` / `DEBUG=false`, restores TLS and volumes while
nothing is running, then builds and starts the prod overlay.

**4. Verify before DNS.** The new host is still invisible to users, which
makes this the cheapest verification you will ever get. Use `--resolve` to
point your own request at the new host without touching DNS:

```bash
curl --resolve engage.blinkconnected.com:443:127.0.0.1 \
     https://engage.blinkconnected.com/api/v1/health/ready

./scripts/verify_backup_restore.sh
./scripts/verify_alerting.sh
```

Then manually: log in, open a conversation, **open an attachment** (the
one check proving database and object storage came from the same set),
and confirm Grafana still has its dashboards and users.

**5. Harden the edge.** The prod overlay now binds backend, Grafana and
Prometheus to `127.0.0.1`. Add the firewall as defence in depth:

```bash
ufw default deny incoming
ufw allow 22/tcp && ufw allow 80/tcp && ufw allow 443/tcp
ufw enable
ss -tulpn | grep -vE '127\.0\.0\.1|\[::1\]'   # expect only 22, 80, 443
```

> **ufw does not constrain Docker.** Published ports are reached through
> the `DOCKER` chain, which iptables traverses before the `INPUT` chain
> ufw manages, so `ufw deny 3000` leaves a published port open. The
> `127.0.0.1` bindings in `docker-compose.prod.yml` are the actual fix.
> Verify with the `ss` line above, not with `ufw status`.

**6. Cut DNS over.** Repoint the A record at the new IP. At a 300s TTL,
most traffic moves within five minutes.

**7. Confirm the certificate renews from the new address.** Let's Encrypt
validates over HTTP to whatever the domain now resolves to, so this only
works after DNS has moved:

```bash
certbot renew --dry-run
```

A migrated certificate that cannot renew is a working platform with a
90-day fuse in it.

## After

- **Leave the old host up, stopped, for 48 hours.** Not running — stopped.
  It is the rollback, and it stops being a valid one the moment it accepts
  a write the new host does not have.
- **Set `BACKUP_REMOTE`.** It is unset today, so every backup set lives on
  the same disk as the database it protects. A fresh host is the moment to
  fix this — see `backup_all.sh`'s header.
- **Store `BACKUP_PASSPHRASE` off-host** in the password manager, if it is
  not already there.
- **Install the backup timers**: `deploy/systemd/install.sh`.
- **Delete the export from both hosts** — it contains `.env` in the clear:
  ```bash
  rm -rf /var/tmp/blinkengage-migration
  ```
- **Re-run the DR rehearsal** on the new host. The measured 4.8s RTO was
  measured on hardware you no longer have:
  ```bash
  BACKUP_PASSPHRASE=<passphrase> ./scripts/dr_rehearsal.sh
  ```
- **Correct `disaster-recovery.md`.** It states "the repository has no
  remote" and that CI has never run. A remote exists now
  (`github.com:Blinkconnected/EngageAI.git`), which changes the full-host-loss
  procedure — `source.bundle` is no longer the only copy of the code.

## Rollback

Before DNS is cut over there is nothing to roll back: the old host is
still serving. After cutover, and while the old host is still stopped and
intact:

1. Repoint the A record back to the old IP.
2. Start the old stack: `docker compose up -d`.
3. Anything written on the new host after cutover is lost — which is why
   the rollback window is short and why the decision to keep the new host
   should be made deliberately rather than by letting 48 hours elapse.

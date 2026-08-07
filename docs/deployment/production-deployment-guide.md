# Production Deployment Guide

**Deploying Blink Engage to production, from an empty host to a
verified running platform.**

Follow this in order. The verification steps are not optional decoration
— several of them exist because the thing they check has silently failed
before.

- Day-to-day operations afterwards: [Operator Runbook](./runbooks.md)
- Recovery: [Disaster Recovery](./disaster-recovery.md)
- Configuring the product: [Administrator Guide](../guides/administrator-guide.md)

---

## 1. Requirements

### Host

| | Minimum | Recommended |
|---|---|---|
| OS | Ubuntu 24.04 LTS | Ubuntu 24.04 LTS |
| CPU | 4 cores | 8 cores |
| RAM | 8 GB | 16 GB |
| Disk | 100 GB SSD | 250 GB SSD |
| Network | Static IP, DNS | Static IP, DNS |

**On disk:** 100 GB is a floor, not a target. The current development
host runs at 93% of 38 GB, and the alert that reports it exists because
a full disk stops Postgres writing and takes the platform down. Size for
attachment growth — object storage dominates over time — and keep
headroom for backups, which are written locally before being shipped
off-host.

### Software

- Docker Engine 24+ and the Compose plugin
- `git`, `gpg`, `rsync`, `tar`, `sha256sum` (all in a base Ubuntu install
  except Docker)

### Off-host

**A separate machine for backups.** This is a requirement, not an
optimisation: a backup on the same disk as the database covers exactly
one failure mode and none of the ones that destroy a platform. It needs
SSH access and enough space for 30 daily sets.

## 2. DNS and TLS

Point your hostname at the host before deploying — certificate issuance
needs it to resolve.

```
engage.example.com.    A    203.0.113.10
```

TLS terminates at nginx. Place your certificate and key where the nginx
configuration expects them, or terminate at a load balancer in front.

## 3. Get the code

```bash
sudo mkdir -p /opt/blinkengage
sudo chown "$USER" /opt/blinkengage
git clone <repository> /opt/blinkengage
cd /opt/blinkengage
git checkout <release-tag>
```

**Check out a tag, not a branch.** A production host tracking a moving
branch will pick up whatever was merged the next time somebody rebuilds.

## 4. Configure

```bash
cp .env.example .env
chmod 600 .env
```

Edit `.env`. Every variable below must be set — the stack refuses to
start without several of them, deliberately.

### Required — the stack will not boot without these

| Variable | Notes |
|---|---|
| `JWT_SECRET_KEY` | `openssl rand -hex 32`. Rotating it signs every user out. |
| `CREDENTIALS_ENCRYPTION_KEY` | Encrypts channel and ERP credentials. **Losing it makes every stored credential unreadable.** |
| `POSTGRES_PASSWORD` | |
| `RABBITMQ_DEFAULT_PASS` | |
| `MINIO_ROOT_PASSWORD` | |
| `S3_SECRET_KEY` | |
| `GF_SECURITY_ADMIN_PASSWORD` | Grafana admin |
| `CORS_ALLOW_ORIGINS` | Explicit origins. A wildcard **refuses to boot** — with `allow_credentials`, it would let any site read authenticated responses. |
| `PUBLIC_BASE_URL` | Used in emails and surveys |
| `ENVIRONMENT` | `production` — disables `/docs`, `/redoc`, `/openapi.json` |

### Required for the platform to be operable

Not enforced at boot, and the platform is not production-ready without
them:

| Variable | Why |
|---|---|
| `ALERT_CRITICAL_WEBHOOK_URL` | Where critical alerts go. Unset means they land in an on-host sink nobody watches at 03:00. |
| `ALERT_WARNING_WEBHOOK_URL` | Warning channel |
| `SMTP_*` | Email notifications and password resets |
| `FCM_SERVICE_ACCOUNT_JSON` | Push notifications. Unset means push is not sent and not marked sent, so configuring later starts working immediately. |

> **These five variables are missing from `.env.example`**
> (`ALERT_CRITICAL_WEBHOOK_URL`, `ALERT_WARNING_WEBHOOK_URL`,
> `BACKUP_REMOTE`, `BACKUP_PASSPHRASE`, `BACKUP_RETENTION_DAYS`).
> Add them by hand until that is fixed —
> [audit finding 5a](../releases/v1.0-engineering-audit.md#5a-five-variables-are-missing-from-envexample-).

### Two variables in `.env.example` do nothing

```
PAYPAL_ENVIRONMENT                      ← dead; use PAYPAL_SANDBOX
BILLING_FAILED_PAYMENTS_BEFORE_SUSPEND  ← dead
```

**`PAYPAL_ENVIRONMENT=live` will not switch you to live payments.** The
setting that works is `PAYPAL_SANDBOX=false`. Recorded as
[TD-1](../releases/v1.0-technical-debt.md#td-1).

### Optional

AI providers (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `OLLAMA_BASE_URL`),
payment providers, ERPNext, rate limits, token lifetimes.

## 5. Start the stack

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

**Both files, always.** The production overlay is what supplies memory
limits, restart policies, health checks and log rotation. The base file
alone runs a development configuration in production.

Migrations run automatically at container start, serialised by a Postgres
advisory lock, so several containers starting at once is safe.

Watch it come up:

```bash
docker compose ps
docker compose logs -f backend
```

## 6. Verify the deployment

Do all six. Each one has failed silently before.

### 6.1 The platform serves

```bash
curl -sf https://engage.example.com/healthz
curl -s https://engage.example.com/api/v1/health/ready | python3 -m json.tool
```

`ready` reports each dependency. All must be reachable.

### 6.2 Every service is healthy

```bash
docker compose ps --format '{{.Service}}\t{{.State}}\t{{.Health}}'
```

No service should be `restarting`, and nothing with a health check should
be `unhealthy`.

### 6.3 Metrics are collected and closed to the public

```bash
curl -s http://localhost:9090/api/v1/query?query=up | python3 -m json.tool | grep -c '"value"'
```

All scrape targets should be `up`. Then confirm `/metrics` is **not**
publicly reachable — from a machine outside your private ranges:

```bash
curl -so /dev/null -w '%{http_code}\n' https://engage.example.com/metrics   # expect 403
```

### 6.4 Alerts actually reach a person

```bash
./scripts/verify_alerting.sh
```

This fires a real alert through the real notification policy and confirms
it arrives. It also fails on any rule that cannot evaluate — the failure
mode that made every rule useless while looking configured.

**Do not skip this.** Configuring alerting and having working alerting
are different properties, and only the second one is worth anything.

### 6.5 Queues have their retry and dead-letter topology

```bash
docker compose exec -T rabbitmq rabbitmqctl list_queues name | grep -cE '\.(retry|dlq)$'
```

Expect **24** — twelve queues, each with a retry and a dead-letter
sibling. A lower number means a consumer did not start.

### 6.6 Backups run, and leave the host

```bash
sudo deploy/systemd/install.sh
sudoedit /etc/blinkengage/backup.env     # BACKUP_PASSPHRASE, BACKUP_REMOTE
sudo systemctl start blinkengage-backup.service
journalctl -u blinkengage-backup.service -n 40 --no-pager
ssh backup@backups.example.com ls /srv/blinkengage/
```

The last command is the one that matters. **The off-host leg has never
been exercised** ([L-3](../releases/v1.0-known-limitations.md)) — until
you see a set on the remote, backups do not survive host loss.

> **Store `BACKUP_PASSPHRASE` off this host**, in the organisation's
> password manager. It decrypts the `.env` inside every backup set. Lost
> with the host, every backed-up credential is unrecoverable — the
> backups would restore a platform that cannot start.

## 7. Rehearse recovery before you need it

```bash
BACKUP_PASSPHRASE=<passphrase> ./scripts/dr_rehearsal.sh
```

Non-destructive: it restores into scratch resources, verifies all four
asset classes, times each phase, and tears everything down. Production is
read from and never written to.

**Do this before the first customer**, not after the first incident. A
recovery plan nobody has executed is a document, not a capability.

## 8. Create the first workspace

Register the first company through the UI at `https://engage.example.com`.
The first registered user becomes its owner.

Registration automatically creates default roles, a **General** queue, a
catch-all routing rule and a **General** service — so routing works
before anything is configured.

Then follow the
[Administrator Guide](../guides/administrator-guide.md#1-setting-up-a-new-workspace).
The one genuinely blocking step is connecting a channel.

## 9. Go-live checklist

- [ ] DNS resolves; TLS valid
- [ ] `ENVIRONMENT=production` (`/docs` returns 404)
- [ ] No placeholder secrets; `.env` is `0600`
- [ ] All services healthy (§6.2)
- [ ] All Prometheus targets up (§6.3)
- [ ] `/metrics` returns 403 publicly (§6.3)
- [ ] `verify_alerting.sh` passes (§6.4)
- [ ] Critical alerts point at a real destination, not the on-host sink
- [ ] 24 retry/DLQ queues present (§6.5)
- [ ] A backup set has landed **off-host** (§6.6)
- [ ] `BACKUP_PASSPHRASE` stored off-host
- [ ] DR rehearsal passed (§7)
- [ ] Disk below 80%
- [ ] SMTP configured and a test email received
- [ ] At least one channel connected **and tested**
- [ ] Business hours configured
- [ ] An on-call rotation exists — alerting is only as good as the person receiving it

## 10. Routine operations

| Task | Cadence | How |
|---|---|---|
| Confirm backups ran | Daily | `systemctl list-timers 'blinkengage-*'` |
| Check disk | Weekly | Alerts, but look anyway |
| Restore drill | Weekly | Automatic — check it passed |
| Full DR rehearsal | Quarterly | `scripts/dr_rehearsal.sh` |
| Re-verify alerting | After any alerting change | `scripts/verify_alerting.sh` |
| Review dead-letter queues | On alert | [DLQ runbook](./runbooks.md#drain-a-dead-letter-queue) |

## 11. Upgrading

```bash
cd /opt/blinkengage
BACKUP_PASSPHRASE=<passphrase> ./scripts/backup_all.sh    # first
git fetch --tags && git checkout <new-tag>
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

Migrations apply automatically on start. Re-run §6 afterwards — a
deployment that comes up is not the same as a deployment that works.

**Rolling back** means checking out the previous tag and rebuilding. If
the release included a migration, roll that back first
([runbook](./runbooks.md#roll-back-a-migration)); the schema must not be
ahead of the code.

---

## See also

- [Operator Runbook](./runbooks.md)
- [Disaster Recovery](./disaster-recovery.md)
- [Go-live checklist](./go-live-checklist.md)
- [Known Limitations](../releases/v1.0-known-limitations.md)
- [Technical Debt Register](../releases/v1.0-technical-debt.md)

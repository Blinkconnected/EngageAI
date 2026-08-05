# Deploying the Learning Platform — Production Pilot

How to turn the Learning Platform on for a pilot, what it will and will
not do once it is on, and how to turn it off.

**It runs in shadow mode and there is no other mode.** No memory fact, no
knowledge suggestion, no candidate event, no notification, no model call.
That is not a switch somebody could flip by accident — the emission code
does not exist, and
[`test_learning_writes_only_its_own_tables.py`](../../backend/tests/unit/test_learning_writes_only_its_own_tables.py)
fails the build if it appears.

---

## What gets deployed

| Component | What it is | Cadence |
|---|---|---|
| `learning-observation-consumer` | Long-running process, own queue | Event-driven |
| `learning-signals-consumer` | Long-running process, own queue | Event-driven |
| `settle-learning-observations` | Celery beat task | 15 min |
| `cluster-learning-observations` | Celery beat task | 1 h |
| `analyse-learning-patterns` | Celery beat task | 24 h |
| `/api/v1/intelligence/*` | Read-only API + one threshold control | — |
| Pattern detection page | Operator dashboard | — |

Four database tables from phase 1 (`learning_observations` and friends)
and four from phase 2 (`learning_clusters`, `learning_cluster_members`,
`learning_trends`, `learning_anomalies`). All eight are **derived and
rebuildable** from the conversations already stored, which is what makes
the rollback below safe.

## Order of operations

The order matters in exactly one place, and getting it wrong is silent.

```bash
# 1. Migrate. Both migrations are additive — new tables only, no ALTER
#    on anything existing — so this is safe with the platform running.
docker compose exec backend alembic upgrade head

# 2. Start the consumers.
docker compose up -d learning-observation-consumer learning-signals-consumer

# 3. Restart beat AND the worker. This is the step that gets missed.
docker compose restart celery-beat celery-worker
```

**Why step 3 is not optional.** Celery beat reads its schedule at
start-up. A beat process that was running before the deploy has no entry
for the learning sweeps, so they never fire — and nothing looks wrong.
Observations accumulate, every one of them stays `pending` forever
because the settle sweep never runs, clustering never sees an eligible
row, and the dashboard reports zeros that look like "no traffic yet"
rather than "the scheduler does not know about this".

This was found during phase 1.5 validation, on a stack where beat had
been up for 41 hours. Verify it took:

```bash
docker compose exec celery-worker python -c "
from blinkengage.core.celery_app import celery_app
print([k for k in celery_app.conf.beat_schedule if 'learning' in k])"
# Expect: settle-learning-observations, cluster-learning-observations,
#         analyse-learning-patterns
```

## Configuration

Everything has a working default. Nothing here costs money — clustering
is lexical, the statistics are arithmetic, and no model is called.

| Setting | Default | What it bounds |
|---|---|---|
| `LEARNING_SETTLE_INTERVAL_SECONDS` | 900 | Settle cadence **and** its run-window width |
| `LEARNING_SETTLE_HOURS` | 72 | How long an outcome may still change |
| `LEARNING_SETTLE_BATCH_SIZE` | 500 | Observations promoted per sweep |
| `LEARNING_CLUSTER_INTERVAL_SECONDS` | 3600 | Clustering cadence and run-window width |
| `LEARNING_CLUSTER_BATCH_SIZE` | 5000 | Observations per company per pass |
| `LEARNING_CLUSTER_COMPANIES_PER_RUN` | 50 | Tenants served per sweep |
| `LEARNING_CLUSTER_LOOKBACK_DAYS` | 14 | How far back a pass looks |
| `LEARNING_CLUSTER_JOIN_THRESHOLD` | 0.15 | Platform default; per-company override available |
| `LEARNING_CLUSTER_MERGE_THRESHOLD` | 0.72 | Platform default; per-company override available |
| `LEARNING_TREND_WINDOWS` / `_WINDOW_DAYS` | 8 / 7 | Trend history |
| `LEARNING_ANALYSIS_INTERVAL_SECONDS` | 86400 | Analysis cadence |

**Two settings must never disagree with their schedule.** The settle and
cluster intervals are used both as the beat cadence *and* as the width of
the window a run claims. They read from one setting for that reason: when
they were two numbers, the window was an hour against a fifteen-minute
cadence, three runs in four collided on the unique constraint and
recorded nothing — including their failures. The health dashboard read
`failed: 0` through a sweep that was failing every time.

### Per company

Learning is off-switchable per company, and independently of Memory:

```json
{ "memory": { "enabled": true, "learning_enabled": true } }
```

A company that switched Memory off has already answered this question —
`is_memory_enabled` is checked first, so the learning flag only ever
narrows. But it can be refused on its own, which is the point: a company
may accept the platform keeping notes on its relationships while refusing
to have those notes mined for patterns.

Turning it off stops observation **at the gate**, before a single message
is read, and writes an `excluded` row recording the refusal. "We saw this
and chose not to learn from it" is a different fact from "we never saw
it", and only the first can be shown to an auditor.

## Verifying the deploy

```bash
# Sweeps ran and recorded a window each.
docker compose exec postgres psql -U blinkengage -d blinkengage -c \
  "select run_type, status, items_in, items_out, errors, window_start
     from learning_runs order by started_at desc limit 5;"
```

Expect one row per run type per window, `status = completed`, `errors = 0`.
Consecutive windows must each produce their own row; two runs inside one
window produce exactly one, which is the constraint working.

Then open **Pattern detection** in the sidebar. The shadow banner is the
first thing on the page. If it is missing, you are not looking at this
build.

## Rolling back

Safe, and safe because clusters are an interpretation rather than a
record.

```bash
# Stop producing.
docker compose stop learning-observation-consumer learning-signals-consumer
docker compose restart celery-beat   # drops the sweeps from the schedule

# Optional: drop phase 2's derived tables. Observations are untouched,
# and the next sweep rebuilds every cluster from them.
docker compose exec backend alembic downgrade e5b2c83f19d7
```

Verified up → down → up against real PostgreSQL. Downgrading phase 2
loses no record: clusters, trends and anomalies are all recomputable from
`learning_observations`, which is why they can be dropped without a
backup step.

To roll back phase 1 as well (`alembic downgrade d3a91c07f2b4`) is also
safe, and it *does* discard the observation record — those cannot be
rebuilt without re-consuming conversation history.

## What to watch in the first week

| Signal | Where | Healthy |
|---|---|---|
| Run errors | Dashboard, "Run errors" | 0 |
| Time since last run | Dashboard, "Since last run" | < 2 h |
| Eligible share | Dashboard, "Eligible" | Rising as the 72 h settle window passes |
| Groups of one | Dashboard, "Groups of one" | < 0.30 |
| Consumer memory | `docker stats` | Flat; ~70 MB each at rest |

The first two are the only ones that indicate a *fault*. The others are
the pilot's actual subject — see the [operator handbook](../architecture/learning-platform-operator-handbook.md).

## See also

- [Operator handbook](../architecture/learning-platform-operator-handbook.md) — how to judge what it finds
- [Dashboard reference](../architecture/learning-platform-dashboard.md) — every number on the page
- [Pilot readiness checklist](../architecture/learning-platform-pilot-checklist.md) — the phase 3 gate
- [Phase 2 design](../architecture/learning-platform-phase-2.md)

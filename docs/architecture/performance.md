# Performance & Load Testing

M28 of the roadmap, continuing Phase 6 (Hardening & Launch). A real load
test against the live stack, two query-optimization fixes it motivated
(verified via `EXPLAIN ANALYZE`, not guessed at), a caching-strategy
review, and a documented (not applied) partitioning playbook for the
`messages` table.

## Load testing: methodology and an honest read of the numbers

`scripts/load_test.py` — a ~160-line async script using `httpx`
(already a runtime dependency) rather than adding Locust/k6 as a new
dependency for what concurrency-controlled request generation plus
p50/p95/p99 latency reporting doesn't need a framework for. It registers
a throwaway company, seeds baseline customers, then runs N concurrent
workers hammering a realistic mix of read/write endpoints
(`list_customers`, `list_conversations`, `get_company`,
`create_customer`) for a configured duration.

```bash
python scripts/load_test.py --base-url http://localhost:8000/api/v1 \
    --concurrency 20 --duration 30
```

Run against the real dev stack, two results matter more than the raw
numbers:

1. **At concurrency=3**: p50 30-45ms across all four endpoints, ~73
   req/s throughput — genuinely fast, healthy baseline latency.
2. **At concurrency=20**: p50 balloons to 190-370ms, p95/p99 into the
   600-2000ms range, and throughput barely rises (~58-83 req/s) —
   the classic signature of a saturated single worker process queuing
   requests rather than the application logic itself being slow.

Comparing the dev target (`uvicorn ... --reload`, effectively one
worker process) against a standalone build of the **production**
runtime target (`--workers 4`, per `docker/backend/Dockerfile`) at the
same concurrency showed a real, consistent improvement (~44% higher
throughput) — confirming horizontal worker scaling behaves as intended
architecturally.

**Honest caveat**: this sandbox has only **2 CPU cores** total, shared
across all 18+ containers in the stack simultaneously (Postgres, Redis,
RabbitMQ, Celery, Grafana, Loki, Prometheus, Promtail, MinIO, nginx, and
the backend itself). The *absolute* millisecond numbers above are not
representative of production hardware and should not be read as SLA
targets — they're an artifact of this specific constrained environment.
The *qualitative* findings (single-worker saturation under concurrent
load; multi-worker configuration meaningfully helps; 0% error rate under
load, meaning nothing crashes or corrupts data under contention) are the
real, reusable result. Re-run this script against real production-class
hardware before treating any specific number as a capacity plan.

## Query optimization: two real index gaps, found and fixed

`EXPLAIN (ANALYZE, BUFFERS)` against the two highest-traffic list
queries — `ConversationRepository.list_for_company` and
`CustomerRepository.list_for_company`'s browse case — showed both doing
an `Index Scan` on the single-column `company_id` index followed by a
**separate in-memory `Sort` step** before the `LIMIT` could apply. At
today's near-zero row counts this costs microseconds and is invisible;
at real per-company volume (thousands of conversations/customers), that
sort would run over every matching row on *every single paginated
request* — the classic index gap that only bites at scale, which is
exactly why this milestone's job is to find it before scale finds it.

Added two partial, pre-sorted composite indexes (migration
`f2a3b4c5d6e7`):

- `ix_conversations_company_last_message` — `(company_id, last_message_at
  DESC NULLS LAST, created_at DESC) WHERE deleted_at IS NULL`, matching
  `list_for_company`'s exact `ORDER BY` so Postgres can satisfy filter +
  sort + `LIMIT` from the index alone. Confirmed via `EXPLAIN ANALYZE`:
  the separate `Sort` node disappeared entirely after the migration —
  straight from `Index Scan` to `Limit`.
- `ix_customers_company_full_name` — `(company_id, full_name) WHERE
  deleted_at IS NULL`, for the equivalent name-sorted browse case.

Both use `DESC`/no explicit `NULLS LAST` for the ORM model's own
`__table_args__` (used by `Base.metadata.create_all` in tests against
SQLite) — SQLite does not support `NULLS LAST` in an index definition at
all (confirmed empirically, not merely undocumented: `sqlite3.
OperationalError: unsupported use of NULLS LAST`). The actual Postgres
schema, governed by the migration rather than the model (the same
per-dialect-nuance precedent `postgresql_where`/`sqlite_where` already
establish elsewhere in this codebase), uses the more precise `DESC NULLS
LAST` to exactly match the query's `ORDER BY` with zero residual sort.

`messages` (`MessageRepository.list_for_conversation`, sorted by
`created_at DESC`, a `NOT NULL` column) already had the right composite
index (`ix_messages_conversation_created`) since M11 — no gap there, no
change needed. Conversation/customer responses never touch a lazy-loaded
relationship when serializing (`ConversationResponse` exposes only
scalar FK columns, never nested customer/agent objects), so there's no
N+1 query problem on these paths either — confirmed by inspection, not
just assumed.

## Caching strategy: validated, not expanded

Current Redis usage: refresh token store, web-chat session store, rate
limit counters, ephemeral realtime pub/sub. Notably, RBAC permissions
are already effectively cached without needing Redis at all — resolved
once at login/refresh time and embedded directly in the JWT's
`permissions` claim, so every subsequent permission check
(`require_permission`) costs zero database round trips for the lifetime
of that access token. This is exactly the right design already in place,
not a gap to fill.

No new caching was added this milestone. Adding a cache without an
evidenced bottleneck driving it would be exactly the kind of premature
optimization this codebase's own engineering principles argue against —
and the load test above didn't surface a caching-shaped bottleneck (the
observed latency was explained entirely by single-worker-process
contention, not by expensive repeated computation or redundant queries
a cache would help with). The one candidate flagged for **future**
consideration, if load testing against real data volume ever shows it
warranted: cached published Knowledge Base articles (a read-heavy,
write-light content type), invalidated on `knowledge_base.updated`-style
events — not implemented now, since there's no evidence it's needed yet.

## `messages` table partitioning: a documented playbook, not applied

The original event-bus/channels design (M11) already flagged native
Postgres range partitioning of `messages` by `created_at` (monthly) as
the right move at real volume — every hot query pattern already includes
a partition-friendly predicate (`conversation_id`/`company_id` +
`created_at`). At today's row count (a handful of dev/test rows),
actually converting the live table now would be pure risk for zero
benefit: partitioning requires recreating the table (Postgres can't
`ALTER TABLE ... PARTITION BY` an existing non-partitioned table
in-place) and is only worth the migration risk once a single table's
size genuinely affects vacuum/index-maintenance/query-planning time —
none of which is true yet.

**When to apply this** (a rough, not precise, trigger): `messages`
approaching tens of millions of rows, or `pg_stat_user_tables` showing
autovacuum/analyze durations climbing on it, or query plans on it
starting to show costly sequential scans despite existing indexes.

**The playbook, ready to execute at that point:**

1. Create a new partitioned table `messages_partitioned` with the exact
   same columns/constraints as `messages`, declared
   `PARTITION BY RANGE (created_at)`.
2. Create monthly partitions covering the existing data's date range
   plus several months ahead (`messages_y2026m01`, `messages_y2026m02`,
   ...) — either by hand or via `pg_partman` (a well-known Postgres
   extension for automating partition creation/retention, worth adding
   as a dependency at that point rather than hand-rolling a cron job).
3. Backfill: `INSERT INTO messages_partitioned SELECT * FROM messages`
   in batches (not one giant transaction) to avoid a multi-hour lock/WAL
   spike on a large table.
4. Inside a single transaction: `ALTER TABLE messages RENAME TO
   messages_old; ALTER TABLE messages_partitioned RENAME TO messages;`
   — an atomic swap, not a rebuild-in-place.
5. Recreate every FK that references `messages.id`
   (`message_attachments.message_id`, `messages.reply_to_message_id`
   self-FK) against the new partitioned table — partitioned tables have
   restrictions on being FK targets in older Postgres versions; confirm
   the deployed Postgres version's support before committing to this
   exact approach (Postgres 17, this project's target, supports
   partitioned tables as FK targets natively).
6. Verify with the same bar every migration in this codebase already
   uses: apply against a real Postgres copy of production data (or a
   representative synthetic volume), `EXPLAIN ANALYZE` the hot queries
   before/after, and confirm application code needs zero changes (a
   partitioned table is queried identically to a normal table from the
   application's point of view — this is purely a storage-layer change).
7. Drop `messages_old` only after a full backup
   (`scripts/backup_postgres.sh`) and a soak period confirming nothing
   regressed.

Not written as an executable Alembic migration in this milestone — a
migration file that does nothing when run against near-empty data isn't
verifiable the way every other migration in this codebase has been
(against real Postgres, with real before/after evidence), and a
partitioning migration is specifically the kind of operation where
"looks right" and "verified against representative data" are very
different bars.

## Verification performed

No new automated tests this milestone (the two new indexes were
verified against real Postgres via `EXPLAIN ANALYZE` before/after, which
is the only meaningful verification for an index — SQLite's query
planner and near-zero test-fixture row counts wouldn't demonstrate
anything). `ruff check`/`ruff format --check`/`mypy src` clean; existing
`test_conversations_api.py`/`test_customers_api.py` suites (18 tests)
still green after the model changes, confirming the new indexes don't
change query *results*, only their *plans*. Migration `f2a3b4c5d6e7`
verified against the real running Postgres via `docker compose exec
backend alembic upgrade head`, a downgrade/re-upgrade cycle, and direct
`\d customers`/`\d conversations` inspection confirming both indexes
exist with the expected definitions.

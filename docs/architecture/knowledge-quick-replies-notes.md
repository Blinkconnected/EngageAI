# Knowledge Base, Quick Replies, Internal Notes

M20 of the roadmap. Three agent-productivity features grouped together
because they're the same shape of problem (a company-scoped catalog an
agent browses or a conversation-scoped annotation) — none of them needed
a new architectural pattern; all three are straightforward applications
of conventions this codebase already established in M7/M8/M14.

## Knowledge Base

`KnowledgeCategory` (self-referential `parent_id`, `SET NULL` on parent
delete — detaches children to top-level rather than cascading, the same
"detach, don't cascade-delete" reasoning Team/Agent already apply to
Department) and `KnowledgeArticle` (`category_id` nullable, `SET NULL`).
Tagging reuses the existing company-scoped `Tag` catalog (M8) via a new
`knowledge_article_tags` join — deliberately not a parallel tagging
system, since `Tag` was already a generic catalog with no hard coupling
to `Customer` beyond the join table `customer_tags` uses.

**Search is a basic case-insensitive `ILIKE` substring match on
title/body** — not semantic or AI-powered. "Knowledge Search"/"FAQ
Search" are explicitly named as AI Engine (M22) features in this
project's spec; building a real search experience now would mean either
committing to a Postgres-only full-text feature (breaking this
codebase's SQLite-test-compatibility convention, e.g. `custom_fields`
staying portable `JSON` not `JSONB`) or guessing at embedding/ranking
infrastructure a full month before the milestone that actually owns it.
Basic substring search is honestly what "browse and filter articles"
needs today; semantic search is a documented extension point for M22,
not built speculatively here.

**Since superseded in scope**, though not yet in code: the
[Company Intelligence Engine](./company-intelligence-engine.md) designs the
replacement — article versioning, chunking, embeddings and hybrid
lexical/vector/graph retrieval, with this table kept and extended rather
than migrated away. Nothing here has changed yet; that document is design
only.

### A repository lesson worth documenting: loaded vs. unloaded collections

Building `KnowledgeArticleRepository.set_tags` initially copied
`CustomerService._set_tags`'s shape but called it on a just-flushed,
never-loaded article — and hit `MissingGreenlet` (SQLAlchemy's async ORM
can't lazy-load a relationship via plain attribute access outside an
explicit query). `CustomerService.create()`'s own comment had already
documented the fix: assign the collection *at construction time* (a
transient object's collection is "loaded" with whatever you assign it,
no DB round-trip), never touch `.the_collection` on an object that's
already persistent but was never eager-loaded. `KnowledgeService.
create_article` was fixed to resolve `Tag` rows first and pass
`article_tags=[...]` into the `KnowledgeArticle(...)` constructor,
exactly like `CustomerService.create()` does — `set_tags` (mutating an
already-loaded collection) stays reserved for `update_article`, where the
article was fetched via `get_by_id` (which eager-loads the collection).

## Quick Replies

`QuickReply`: company-wide (not department/team-scoped — a real scope
restriction could be added later as a nullable FK without a breaking
change, not built speculatively now), a `shortcut` (slash-command-style
trigger, e.g. `/refund`) unique per company among active rows (the same
partial-unique-index pattern `Queue.name`/`Customer.email` already use).
`QuickReplyService.create`/`update` explicitly check
`get_by_shortcut` before inserting and raise `EntityAlreadyExistsError`
(409) — mirroring `QueueService`'s explicit-check-before-insert pattern,
rather than letting the partial unique index's `IntegrityError` surface
as an unhandled 500.

## Internal Notes

A genuinely separate table (`InternalNote`), not a third `MessageDirection`
value on the M13 `messages` table. A note was never sent through any
channel provider (`Message.channel_type`/`channel_config_id` are `NOT
NULL` by design), has no delivery/read status, and doesn't participate in
conversation-reopen-on-new-message logic. Reusing `Message` would mean
either loosening its `NOT NULL` constraints for every already-shipped row
or special-casing "is this actually a note?" throughout code that
currently assumes every message is inbound or outbound — a genuinely
separate concept earns a genuinely separate table.

Routes live nested under `/conversations/{id}/notes` inside
`conversations.py` (not a new router file) — this mirrors the existing
`/conversations/{id}/messages` and `/conversations/{id}/attachments`
sub-resource pattern already in that file. No new permission: creating/
viewing a note is gated by the same `conversations.manage`/
`conversations.read` a reply already requires — a note is just another
way to interact with a conversation the agent already has access to, and
a dedicated `internal_notes.*` permission would only fragment that
without a real access-control need behind it.

Hard-deletable (no `SoftDeleteMixin`) — same reasoning as `RoutingRule`:
low-stakes, no compliance requirement to retain a deleted note, and the
audit-log-consumer (bound to `#`, M9) already durably records the
`internal_note.deleted` domain event regardless of the row's fate.

## Schema impact

Five new tables: `knowledge_categories`, `knowledge_articles`,
`knowledge_article_tags`, `quick_replies`, `internal_notes`. New
permissions: `knowledge_base.read`/`manage`, `quick_replies.read`/
`manage` (Owner/Admin get both; Agent gets read-only, mirroring
`queues.read`-only for Agent). No new permission for internal notes, per
above.

## Verification performed

23 new tests added (332 → 355 passing), all green under `pytest -q`,
`ruff check`/`ruff format --check`, and `mypy src`:

- `tests/integration/test_knowledge_api.py` (11 tests) — category CRUD
  and nesting, article CRUD with tags (create-with-tags, update-replaces-
  tags), pagination, substring search across title/body, soft delete,
  company scoping, authentication.
- `tests/integration/test_quick_replies_api.py` (7 tests) — CRUD,
  pagination, search across shortcut/title, the `EntityAlreadyExistsError`
  409 on a duplicate shortcut, company scoping, authentication.
- `tests/integration/test_internal_notes_api.py` (5 tests) — create/list/
  update/delete against a real conversation (seeded through the same
  `handle_message_received` path other consumer tests use), confirming
  notes never appear in the `/messages` thread, a 404 for a nonexistent
  conversation, authentication.

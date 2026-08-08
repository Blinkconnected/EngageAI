# Global Search

One search box (`GET /search`, Ctrl/Cmd-K anywhere in the app) that spans
fifteen entity types at once.

**Work** — conversations, customers, agents, knowledge base articles and
categories, quick replies, teams, queues, workflows.

**Configuration** — FAQs, services, departments, channels, SLA policies,
roles.

The configuration half is what makes this "search everything" rather
than "search the inbox". An administrator asked to change *the Platinum
SLA* or *the Riyadh department* arrives knowing a name and nothing else;
without those types the only route to them was remembering which of a
dozen settings pages each one lives on. They are ordered after the work
entities so an agent searching a customer's name never has to scroll
past a queue that happens to share a word.

## One endpoint, fifteen permissions

Every other list endpoint in this codebase is gated by exactly one
`require_permission(...)` on the route. Global search can't be: one
request spans fifteen entity types with fifteen different permissions,
and a route-level gate on any single one of them would 403 a caller who
legitimately can't read that one type but can read the rest.

So `GET /search` is gated on **authentication only**
(`enforce_search_rate_limit`, which depends on `get_current_auth`), and
`SearchService` filters per entity type against the caller's own
`AuthContext.permissions`. A caller only ever gets results from types
they could already open directly.

The response reports `searched_entity_types` — what the caller's
permissions actually allowed — so the UI can distinguish "we searched
workflows and found nothing" from "we never searched workflows." A
caller with *no* readable types gets an empty result, not a 403:
degrading is what lets one endpoint serve callers with wildly different
permission sets.

## Why a dedicated repository, not the existing list endpoints

The roadmap item said "reuse existing backend APIs wherever possible,"
and four of the types (customers, agents, quick replies, KB articles)
already accept a `search` param. Reusing those
`list_for_company(search=...)` methods verbatim was the obvious reading
— and the wrong call:

- **Twice the queries.** Each list method also runs a separate
  `COUNT(*)` over the same filtered subquery to populate `Page.total`,
  which global search never shows (it shows "top 5 per type", not "1 of
  4,213").
- **Eager loads search doesn't need.** `CustomerRepository` pulls
  `customer_tags -> tag`; `AgentRepository` pulls `user` + `department` +
  `team_memberships -> team`; `TeamRepository` pulls its members. All
  wasted for a row that renders as a title and a subtitle.

`SearchRepository` instead runs one lean, capped, column-projected query
per type. What *is* reused is the convention, exactly: the same `search`
semantics, the same `f"%{term}%"` + `ilike` idiom, the same company
scoping and `deleted_at IS NULL` filters, and — critically — **the same
searchable columns each entity's own list endpoint already searches**, so
a global-search hit and that entity's own filtered list can never
disagree about what matches.

Several types gained text search they never had: **queues** and
**teams** (name + description), **conversations**, and every
configuration type below.

Two of them match on more than their own name, because the name somebody
typed in is rarely the name a thing is known by:

- **Channels** match on `channel_type` as well as `display_name`. The
  person hunting for the WhatsApp channel searches "whatsapp"; whoever
  set it up called it "Main line".
- **Services** match on `code` as well as name and description. Routing
  rules and integrations refer to services by code, so a code is what an
  administrator arrives with when tracing where a rule points.

**FAQs match on their answer as well as their question**, and the
question is what the result row shows. A question reads "Do you
deliver?"; what makes it the right FAQ is the city named in the answer.
Matching questions alone would miss the entry that answers exactly what
was asked. Answers run to paragraphs, so the subtitle is flattened to
one line and cut at 120 characters (`SearchRepository._snippet`) — sent
whole, one FAQ would push every other result off the screen and its
newlines would break the single-line layout the other types use.

Unpublished FAQs are returned rather than filtered out: an administrator
searching their own knowledge needs to find the draft they are part-way
through writing. Published ones are ordered first, so what customers can
actually see outranks a draft when the per-type cap bites.

**SLA policies and roles have no soft-delete column**, unlike most
models here, so those two methods alone have no `deleted_at IS NULL`
filter. Everything else is company-scoped, soft-delete filtered and
capped identically.

**Roles are gated on `roles.manage`**, which is stricter than every
other type here — there is no `roles.read` to fall back on. That is the
right level: a list of role names is a sketch of how a company delegates
authority, which is not something an agent needs and not something to
hand out through a search box.

## Conversations are matched through their customer

A `Conversation` has no title, subject, or name column at all — nothing
to match a search term against, and nothing to label a result row with.
`GET /conversations` accordingly has no `search` param and never has.

Global search matches (and labels) a conversation **through its
customer** — `Customer.full_name`/`email` via a join — which is how the
Inbox already identifies a conversation to an agent. This is the only
place conversations are text-searchable in the product.

Deliberately *not* searching `Message.body`: it's the single most
expensive column in the schema to scan, it would return the same
conversation many times over, and "find the conversation with this
person" is the actual job an agent needs done. Full-text message search
is a genuine future feature, and would want a real index (see below),
not an `ILIKE` bolted onto this fan-out.

## Cost controls

Every existing search in this codebase is a leading-wildcard
`ILIKE '%term%'`, which **cannot use a btree index** — each one is a
sequential scan. Fanning fifteen of those out on every keystroke is
exactly the pathological case, so four things bound it:

The configuration tables added here are the cheap half of the fan-out —
departments, channels, services and SLA policies are counted in tens per
tenant, not the hundreds of thousands conversations and customers reach.
FAQs are the one to watch, since its answer column is long-form text.

1. **Minimum query length (2 chars)** — enforced in `SearchService`, not
   only in the UI, so a direct API caller can't trigger the fan-out with
   a single character either. `ILIKE '%a%'` across every searchable
   table matches nearly everything while telling the caller nothing.
2. **Per-type cap (5)** — global search is a "jump to the thing I'm
   thinking of" affordance, not a report. More matches than that is a
   signal to open that entity's own paginated list page.
3. **Per-user rate limit** (`enforce_search_rate_limit`,
   `search_rate_limit_per_minute`, default 60/min) — per *user*, not per
   IP, for the same reason `enforce_ai_rate_limit` is: several agents
   legitimately share one office IP. Higher than the AI/test-connection
   limits because typeahead is genuinely interactive.
4. **250 ms frontend debounce** (`useDebouncedValue`) — the polite half
   of the pair. The rate limit is the enforcement; this just avoids
   asking in the first place.

The queries run **sequentially, not via `asyncio.gather`**: they share
one request-scoped `AsyncSession`, and a SQLAlchemy `AsyncSession` is
explicitly not safe for concurrent use — gathering would interleave
statements on one connection and raise `InterfaceError` under load.

**If search volume ever outgrows this**, the fix is a real index
(Postgres `tsvector` + GIN, or `pg_trgm` for substring matching), not
more parallelism. Nothing in the current design blocks that: the swap
would be confined to `SearchRepository`'s per-type methods.

## Five entity types have no page to open

Knowledge Base, FAQs, Quick Replies, Teams, and Workflows are fully built
and searchable on the backend but have **no frontend route at all** (see
`AppRoutes.tsx` — no page, no nav entry, no API client). Their search
results are still returned and still rendered, as **disabled rows
labelled "No page for this yet"**, rather than hidden.

Showing them is the honest option: the match is real, and silently
dropping it would make search look broken to anyone who knows the record
exists. They become navigable for free the moment those pages get built
— only `SEARCH_RESULT_PATHS` in `features/search/types.ts` changes.

Queues, Agents, Departments, Services, Channels, SLA policies and Roles
have a list page but no per-entity detail route, so they deep-link to
the list.

## The registry is a contract in three places

`_SEARCHABLES` in `search_service.py` names an entity type, a permission
and a repository method. Nothing at import time checks that the method
exists, that the permission is real, or that the API's
`SearchEntityType` literal knows the type — the first two fail at
request time, and the third fails as a response validation error only
once something actually matches. Adding a type is exactly when somebody
updates two of the three and not the third, so
`tests/unit/test_search_registry.py` checks all of them, and
`features/search/types.test.ts` does the same for the frontend's render
order, route map and en/ar group labels.

The permission-filtering integration test derives its revoke set from
`_SEARCHABLES` rather than listing codes by hand: a new searchable type
would otherwise leave the test's agent able to read one thing, and it
would keep passing while proving nothing.

## Frontend

- `features/search/GlobalSearchDialog.tsx` — a MUI `Dialog` anchored near
  the top (a vertically-centered one would jump on every keystroke as
  results grow), opened from an AppBar search button or Ctrl/Cmd-K.
- The Ctrl/Cmd-K listener is bound on `window` (it must work regardless
  of focus) but **ignores keystrokes while a text field is focused**, so
  it can never swallow a genuine Ctrl-K inside an input.
- Results are grouped into **one `<List>` per entity type, each with its
  own `aria-label`**, rather than a single list with `ListSubheader`s.
  Scoping subheaders properly requires nesting a `<ul>` inside an `<li>`,
  which axe flags — and separate labelled lists read better anyway
  ("Customers, list, 3 items"). Each row is a `ListItem` (an `<li>`)
  wrapping a `ListItemButton`, since a bare `ListItemButton` renders a
  `<div>` directly inside the `<ul>`, which is invalid list markup.

## Verification performed

15 new tests, all green under `pytest -q`, `ruff check`, `mypy src`,
`tsc`, `eslint`, `vitest`, and `vite build`:

- `tests/integration/test_search_api.py` (14) — matching a
  customer by name/email/phone; a queue by name *and* description
  (search-only behavior, since `GET /queues` has no `search` param, so
  this proves the new repository rather than a pre-existing one); teams,
  quick replies and KB articles in one query; a conversation found via
  its customer's name; the 2-character floor returning nothing;
  **company scoping** (company B can't find company A's customer);
  **per-type permission filtering** (a caller with `queues.read`/
  `workflows.read` revoked gets neither those results nor those types
  listed as searched, while a matching queue is proven to exist by
  searching as the owner); a caller with no readable types getting an
  empty result rather than a 403; unauthenticated access rejected; every
  configuration type found by name; a channel found by its *type* and a
  service by its *code*; an FAQ found by words appearing only in its
  answer; a long FAQ answer shortened to a single line; and a role
  visible to the owner but neither returned to nor searched for an agent
  without `roles.manage`.
- `tests/unit/test_search_registry.py` (5, new file) — every searchable
  names a real repository method and a real permission code, the API
  literal and the registry agree in both directions, and no two entries
  share an entity type.
- `features/search/types.test.ts` (4, new file) — every type in the
  render order has a route decision and a label in both English and
  Arabic, the render order and route map agree, and no label is left
  behind for a type that is no longer returned.
- `features/search/GlobalSearchDialog.test.tsx` (6, new file) — the
  minimum-length prompt, grouping by entity type, navigating to a
  customer on select, **disabled non-navigable rows** for types with no
  page, the empty state, and an axe pass with results shown.

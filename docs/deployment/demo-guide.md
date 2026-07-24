# Demo Guide

A complete, honest guide to manually validating the current build — what's
real, how to run it, and exactly how to click through every implemented
feature. Written for a human tester, not another milestone's audience.

## 1. URLs

| URL | What it is |
|---|---|
| **http://localhost/** | **The app.** Everything below happens here. |
| http://localhost:8000/docs | Swagger UI (interactive API reference) — backend port directly, **not** through NGINX (see the caveat in section 7) |
| http://localhost:8000/redoc | ReDoc (read-only API reference), same direct-port caveat |
| http://localhost:3000 | Grafana (dashboards for Postgres/Redis/RabbitMQ/Celery/logs) |
| http://localhost:9090 | Prometheus |

If you're accessing this sandbox remotely through VS Code, use the
**Ports** tab to open the forwarded port (80 for the app).

## 2. Credentials

A demo company already exists (seeded this session — see section 5).

| Role | Email | Password |
|---|---|---|
| Owner (full permissions) | `owner@blinkdemo.io` | `DemoPass123!` |
| Agent (restricted permissions — good for testing RBAC/403s) | `agent@blinkdemo.io` | `AgentPass123!` |

Company: **Blink Demo**.

You can also create your own company from scratch at any time via
**"Create your company"** on the login page — that's a real, first-class
feature (`POST /auth/register`), not a seeded shortcut.

## 3. Starting from scratch

If the stack is already running (check with `docker compose ps`), skip to
section 6 — the demo company above already exists. If you want to verify
the *entire* bootstrap process from zero:

```bash
cd /root/BlinkEngage
git status   # make sure there's nothing uncommitted you'd lose

# Full reset (deletes ALL data — Postgres, Redis, RabbitMQ, MinIO volumes):
docker compose down -v

cp .env.example .env
# Edit .env and replace every "change-me-..." placeholder with a real
# value (JWT_SECRET_KEY, CREDENTIALS_ENCRYPTION_KEY, POSTGRES_PASSWORD,
# RABBITMQ_DEFAULT_PASS, MINIO_ROOT_PASSWORD/S3_SECRET_KEY,
# GF_SECURITY_ADMIN_PASSWORD) — docker compose refuses to start with any
# of these left unset, by design.

docker compose up -d --build
```

First boot takes a few minutes (image builds, Postgres init, Alembic
migrations run automatically via each service's entrypoint). Watch it
come up:

```bash
docker compose ps                              # everything should reach "healthy" or "running"
curl http://localhost/api/v1/health/ready      # {"status": "ok", ...} once ready
```

Then re-seed the demo company, agent, channels, and two live
conversations in one step:

```bash
backend/.venv/bin/python scripts/seed_demo_data.py
```

The script is idempotent — safe to re-run any time; it detects what
already exists and skips it rather than duplicating.

## 4. Required Docker commands (reference)

```bash
docker compose up -d --build      # build + start everything, detached
docker compose ps                 # status of every service
docker compose logs -f backend    # tail one service's logs (swap the name)
docker compose restart backend    # restart one service (picks up code/config changes)
docker compose down               # stop everything, KEEP volumes (data survives)
docker compose down -v            # stop everything, DELETE volumes (data loss — full reset)
docker compose exec backend bash  # shell into a running container
```

Full reference: `docs/deployment/local-development.md` (day-to-day dev)
and `docs/deployment/runbooks.md` (restart/rebuild/migration/rotation
procedures for anything less routine).

## 5. Demo data already loaded

Running right now, in the live Postgres volume:

- **Company**: Blink Demo (`owner@blinkdemo.io` / `DemoPass123!`)
- **Agent**: Alex Agent (`agent@blinkdemo.io` / `AgentPass123!`)
- **Channels**: "Support WhatsApp" (WhatsApp, placeholder credentials —
  see limitations) and "Website Chat" (Web Chat, fully functional)
- **Customers / conversations**: Priya Sharma (tagged `vip`, one open
  conversation asking about a late laptop order) and Marco Rossi (one
  open conversation asking about shipping to Canada) — both created by
  simulating real customer messages over the Web Chat WebSocket, so
  they're genuine database rows, not fixtures.

This lives in the dev Postgres volume — it survives `docker compose
restart`/`down` (without `-v`) but is wiped by `docker compose down -v`.
Re-run `scripts/seed_demo_data.py` after a full reset to get it back.

## 6. Step-by-step walkthrough

### Authentication
1. Open `http://localhost` → redirects to `/login`.
2. Sign in as the Owner (`owner@blinkdemo.io` / `DemoPass123!`).
3. Sign out (avatar menu, top right) and try **"Create your company"**
   instead — fill in any company name/email/password (10+ characters,
   letter + digit) to see the self-serve signup flow. It creates a real
   company + owner + default roles in one call and logs you in
   immediately. Sign back in as the demo Owner afterward.

### Dashboard
4. Land on `/` after login — live counts (open/pending/resolved/closed
   conversations, agent online/away/offline, queue depth), pulled from
   `GET /reports/live-dashboard` every 30 seconds.

### Company Management
5. Sidebar → **Company settings** (`/settings/company`). Change the name,
   save, watch it update in the top bar immediately.

### Customer Management
6. Sidebar → **Customers** (`/customers`) — Priya Sharma and Marco Rossi
   are listed. Try the search box (filters by name/email server-side).
7. Click a row to open their profile. Click **Edit** — change name,
   email, phone, or tags (comma-separated) and save.

### Customer Timeline
8. Still on a customer profile, the **Timeline** tab lists every
   conversation that customer has had, newest first. Click one to jump
   straight into the Conversation View.

### ERPNext Customer View
9. Same profile, **ERPNext** tab — shows "No ERPNext records yet" until
   an ERPNext connection exists (next step).
10. Sidebar → **ERPNext** (`/erp-configs`). Fill in any site URL / API
    key / API secret and submit — this is a real, working connect flow,
    but see section 8 for what it can't do without a genuine ERPNext
    instance behind it.

### Channel Management
11. Sidebar → **Channels** (`/channels`) — "Support WhatsApp" and
    "Website Chat" are both listed as Active. Click the edit icon on one
    to change its name or deactivate it; click delete to disconnect it
    (confirmation dialog first).

### WhatsApp Connection
12. On Channels, click **Connect channel**. WhatsApp is the default type
    — fill in any phone number ID / access token / verify token and
    submit. You'll land on a success screen showing the real webhook URL
    (constructed from your browser's own origin) and the verify token —
    exactly what you'd paste into Meta's App Dashboard for a real
    integration.

### Inbox
13. Sidebar → **Inbox** (`/conversations`). Both demo conversations are
    there, status **Open**. Try the status tabs (All/Open/Pending/
    Resolved/Closed).
14. Click into Priya Sharma's conversation: message thread, a reply box
    (try sending a reply — it appears immediately), an attachment button
    (attach any file), an **Internal notes** tab (visible only to your
    team), and a sidebar to change status, assign an agent, or assign a
    queue.

### Live Conversations
15. With the Inbox open in a browser tab, run this from a terminal to
    simulate a **new customer message arriving live** (the channel-config
    id below is this session's seeded "Website Chat" channel — if you
    reseeded from scratch, get the current one from the Channels page's
    row, or `GET /api/v1/channel-configs`):
    ```bash
    cd /root/BlinkEngage
    backend/.venv/bin/python scripts/simulate_customer_message.py \
      --channel-config-id 4f8dd5ec-4938-4203-b320-11156543671d \
      --message "Hi, is anyone available to help?"
    ```
16. Refresh the Inbox (or wait up to 30s for the poll) to see the new
    conversation appear. Reply to it, then re-run the script with
    `--session-token <token printed by the previous run>` to send a
    follow-up as the *same* customer into the *same* thread.
17. Open the notification bell (top bar) — unread count and a live-pushed
    list, backed by a real WebSocket (`/api/v1/ws/agent`) plus independent
    polling as the durable fallback.

### A few things worth trying deliberately
- **RBAC in action**: sign out, sign back in as the Agent
  (`agent@blinkdemo.io` / `AgentPass123!`), and try to open **Channels**,
  **ERPNext**, or **Company settings** — the Agent role lacks those
  permissions, so you'll land on a real 403 page, and those sidebar items
  won't even appear for that user.
- **Dark mode / RTL**: top bar has a theme toggle (light/dark) and a
  direction toggle (LTR/RTL) — try both.
- **404 page**: navigate to any nonexistent path, e.g. `/nope`.

## 7. Known limitations

- **No embeddable customer-facing chat widget.** Web Chat's backend
  WebSocket gateway is real and fully wired (this is what the demo
  conversations were created through), but there's no polished
  customer-side UI for it yet — `scripts/simulate_customer_message.py`
  stands in for one.
- **WhatsApp/ERPNext connections work but can't reach real external
  services** in this environment — no genuine Meta Business account or
  ERPNext instance is configured behind them. The entire connect/edit/
  disconnect UI and the webhook-URL construction are real and verified;
  actually sending/receiving through them needs your own provider
  credentials.
- **Swagger UI/ReDoc are only reachable on the backend port directly**
  (`http://localhost:8000/docs`), not through NGINX at `http://localhost/...`
  — NGINX's dev config proxies every path it doesn't explicitly recognize
  (including bare `/docs`) to the frontend's Vite dev server, not the
  backend. (Found and fixed as a documentation bug during this session;
  see the README/local-development.md history.)
- **Inbox and notifications refresh on a 30-second poll**, not instantly
  — the WebSocket carries live pushes for notifications specifically, but
  polling is the documented, durable fallback, not a bug.
- **Message history caps at 100 messages** per conversation via "load
  older" — a documented, deliberate limit (see
  `docs/architecture/frontend.md`), not silently missing data.
- **This sandbox has 2 CPU cores and ~3.7GB RAM** shared across ~20
  containers — if the UI feels sluggish under heavy concurrent load,
  that's this environment, not the application (see
  `docs/architecture/performance.md`'s M28 load-test findings for the
  same caveat measured directly).
- **Frontend JS bundle is a single ~1.2MB chunk** (not yet code-split by
  route) — noted, not yet addressed; doesn't affect functionality.

## 8. Placeholder vs. production-ready

**Production-ready** (real, working, exercised against the live backend
this session, not mocked):

- Authentication — login, self-serve company registration, JWT refresh,
  logout
- Dashboard (live data)
- Company settings
- Agents — full create/edit/delete
- Channels — full create/edit/delete, WhatsApp's guided connect form,
  generic JSON credentials for the other five channel types
- Customers — full create/edit/delete, search
- Customer Timeline (composed from real conversation data)
- ERPNext config connect/disconnect + per-customer synced-record display
  (generic, doctype-agnostic rendering)
- Inbox — list, status filter, pagination
- Conversation View — real-time message thread, reply with attachments,
  internal notes, status/assign-agent/assign-queue changes
- Notifications — durable inbox + live WebSocket push
- Realtime — typing indicators, agent online/away/offline presence

**Real UI, but needs external setup to be fully functional:**

- WhatsApp connection (needs a real Meta Business account)
- ERPNext sync/pull (needs a real ERPNext instance)

**Not yet built** (explicitly scoped to later milestones on
`docs/ROADMAP.md`, not started or only partially covered):

- Reports pages (executive/agent/conversation/performance/queue/SLA/CSAT/
  AI dashboards) — backend complete, no frontend yet
- Departments, Teams, Queues, Routing Rules, Workflows, Knowledge Base,
  Quick Replies management UIs — backend complete; only minimal
  read-only lookups exist on the frontend (e.g. the department/queue
  pickers), not full management pages
- Audit log viewer UI — backend complete (`GET /audit-logs`, including
  PDF/Excel export), no frontend page
- A systematic accessibility/responsive-design audit pass (individual
  pages are checked with `vitest-axe` as they're built, but there's no
  dedicated cross-cutting pass yet)
- A full Docker-based production-build smoke test of the entire golden
  path (the production image builds and individual pieces are verified;
  a dedicated end-to-end pass against the built artifact, not just the
  dev server, hasn't been run yet)

# Frontend Architecture

## Stack

Vite + React 19 + TypeScript, Material UI (MUI) v9, Redux Toolkit,
React Query (`@tanstack/react-query`), React Router v7, Axios.

## Structure

```
frontend/src/
  app/                Composition root: Redux store, typed hooks, React
                      Query client, theme provider, route table
                      (AppProviders, AppRoutes, AppThemeProvider).
  theme/              MUI theme + emotion cache (LTR/RTL) factory functions.
  features/           Feature-sliced modules; each owns its Redux slice (if
                      any), API hooks, and page/component components
                      (`features/auth`, `features/session`, `features/ui`,
                      `features/layout`, `features/dashboard`,
                      `features/agents`, `features/channels`,
                      `features/conversations`, `features/customers`,
                      `features/erp`, `features/reports`,
                      `features/notifications`, `features/company`).
                      Each feature's route-level component is named
                      `<Feature>Page.tsx` and is wired directly into
                      `app/AppRoutes.tsx` — there is no separate `pages/`
                      indirection once a page has real state, since nearly
                      every page in this app does.
  shared/
    api/              Axios instance with auth header + refresh-token
                      interceptor (`client.ts`), the generic `Page<T>`
                      pagination type and a `usePaginationParams` hook
                      (`pagination.ts`), and API-error-to-message
                      extraction (`errors.ts`) — shared across features.
    components/       Reusable, feature-agnostic UI primitives: `PageHeader`,
                      `DataTable` (thin wrapper over MUI X Data Grid),
                      `ConfirmDialog`, `FormDialog`, `EmptyState`,
                      `ErrorState`, `LoadingState`.
    hooks/            `usePermissions` and other cross-feature hooks.
  pages/              Only truly generic, stateless routes: `NotFoundPage`
                      (404), `ForbiddenPage` (403).
  test/               Vitest setup (jest-dom matchers, MSW server).
  mocks/              MSW request handlers and server setup, one handler
                      module per feature, composed in `test/setup.ts`.
```

## Branding

Blink Engage adopts the Blink Connected brand identity:

- **Colors**: primary `#8CC63F` (brand green, dark variant `#6BA82D`) on a
  warm near-black `#171412`; light-mode background `#F2F2F0`; divider
  `#E4E3E1`.
- **Typography**: "Baloo 2" for headings (h1–h6), "Nunito Sans" for body
  text and UI chrome — loaded via Google Fonts in `index.html`.
- **Shape**: 12px base border radius, pill-shaped (`border-radius: 999px`)
  buttons and chips, soft low-opacity shadows instead of MUI's default
  heavy elevation, a subtle brand-green glow on primary button hover.

Theme construction lives in `theme/theme.ts` (`createAppTheme(mode,
direction)`) and `theme/emotionCache.ts` (RTL-aware Emotion cache using
`stylis-plugin-rtl`).

## State management

- **Redux Toolkit** (`app/store.ts`) owns cross-cutting *client* state only:
  `auth` (access/refresh tokens — nothing else — persisted to
  `sessionStorage`/`localStorage`) and `ui` (theme mode + text direction,
  persisted to `localStorage`, defaulting to the OS `prefers-color-scheme`).
- **React Query** owns all server state, including the current user's
  profile. There is no `user` object in Redux — see below.
- Page-local filter/pagination state that must survive a round trip to a
  sibling route (not a nested one) lives in the URL via `useSearchParams`
  instead of `useState` — `InboxPage.tsx` is the reference: navigating to
  `/conversations/:id` and back fully unmounts/remounts `InboxPage`, so
  local state would silently reset, but the URL (and a `replace: true`
  history entry so filter changes don't spam browser Back) survives.

## Authentication flow

The backend's `POST /auth/login` and `POST /auth/refresh` return **only**
`{access_token, refresh_token, token_type}` — no user profile, no role
names, no permission list (those live inside the JWT's claims, which the
frontend deliberately never decodes client-side; the one exception is
`POST /auth/register`, whose response *does* include the created user's
full profile, since it's also the first record of that user existing).
The authoritative source for "who is this and what can they do" is always
`GET /auth/me`, called once after tokens are set and cached via React
Query (`features/session/api.ts`'s `useCurrentUserQuery`, query key
`['session', 'me']`, `enabled: isAuthenticated`).

- `shared/api/client.ts` attaches the current access token to every
  request and, on a `401`, transparently calls `/auth/refresh` once
  (de-duplicated via a shared in-flight promise) before retrying the
  original request. A failed refresh logs the user out and clears the
  `['session']` query cache.
- `features/auth/ProtectedRoute.tsx` gates authenticated routes, redirects
  to `/login` (preserving the original destination) if no token is
  present, and renders a full-page loading state while `/auth/me` is
  in flight so gated navigation never flashes the wrong items.
- `features/auth/RegisterPage.tsx` is the "Create Company" flow —
  `POST /auth/register` with `{company_name, owner_full_name, owner_email,
  owner_password}` creates the company, its Owner user, and default
  Owner/Admin/Agent roles in one call, and returns tokens — the caller is
  authenticated immediately, no separate login step needed. On success the
  response's `user` profile is written directly into the `['session',
  'me']` query cache (`queryClient.setQueryData`) to avoid an immediate
  redundant `/auth/me` round trip.
- `shared/hooks/usePermissions.ts` reads `useCurrentUserQuery().data
  ?.permissions` and exposes `hasPermission(code)` / `hasAnyPermission
  (codes)`. `features/layout/RequirePermission.tsx` wraps a route element
  and renders `pages/ForbiddenPage` if the current user lacks the required
  permission — pure UX defense-in-depth; the backend enforces every
  permission independently and is the real gate.

## Localization (i18n) and RTL

Full interface translation, not just RTL layout mirroring:

- **`i18next` + `react-i18next`** (`src/i18n/index.ts`) register one
  namespace per feature directory (`src/locales/en/<ns>.json` /
  `src/locales/ar/<ns>.json`, e.g. `agents`, `conversationsCore`,
  `companySettings` — a few larger directories are split into two
  namespaces, e.g. `channelsCore`/`channelsFields`; see the file for the
  full list). All namespaces are bundled and registered up front — no
  lazy backend/HTTP loading — so `i18next.init()` resolves synchronously
  and `t(...)` is correct on a component's very first render, in both the
  real app and in vitest.
- Each JSON catalog's top-level keys are the component's filename (e.g.
  `{"AgentsPage": {"title": "...", ...}}`); every component using
  translated text calls `const { t } = useTranslation('<namespace>')` and
  renders `t('ComponentName.keyName')`. A `useMemo` that builds
  translated content (e.g. DataGrid `columns`) must include `i18n.language`
  in its dependency array alongside `t` — otherwise memoized content
  won't re-translate if the language changes while already mounted
  (`t` itself doesn't change identity on a language change, so ESLint's
  `react-hooks/exhaustive-deps` can't see this dependency and flags it as
  "unnecessary" — suppressed per-line with an explanatory comment where
  this applies, rather than disabling the rule project-wide).
- **Language source of truth**: `company.settings.language` (Settings →
  Language), the same company-wide setting every other Settings tab
  already uses (Branding, Timezone, Business Hours) — not a personal
  per-browser preference. `useLanguageSync` (`src/i18n/useLanguageSync.ts`,
  mounted once in `AppLayout`) calls `i18next.changeLanguage(...)`
  whenever `company.settings.language` changes, and defaults direction
  to match (`ar` → `rtl`, everything else → `ltr`). Only languages with a
  real translation catalog are offered in the Settings dropdown
  (`SUPPORTED_I18N_LANGUAGES` in `src/i18n/index.ts`, currently `en`/`ar`)
  — `company/types.ts`'s `SUPPORTED_LANGUAGE` type still lists a couple
  more (kept for backward compatibility with any already-stored value)
  that aren't offered until they have their own catalog.
- Direction (`ltr`/`rtl`) itself remains independent `ui` Redux state, as
  before — the topbar's manual "Toggle language direction" button still
  works as a same-session override after the language-driven default is
  applied. Toggling it flips `document.documentElement[dir]`, swaps the
  Emotion cache (so MUI's `sx`/`styled` output gets RTL-flipped via
  `stylis-plugin-rtl`), and MUI's `theme.direction` is kept in sync so
  component internals (e.g. drawer anchoring) also flip.
- **Scope of this pass**: the full authenticated app shell and every
  feature page's UI chrome. Deliberately out of scope: the small set of
  public/pre-auth pages with no company context to source a language
  from (login, register, the public Changelog, the customer-facing CSAT
  feedback page — these stay English-only for now); backend-generated
  dynamic text (notification titles/bodies, since `Notification` has no
  locale field); and a handful of `.ts` (non-component) utility functions
  that map a data code to a human label (e.g. `channelTypeLabel()`),
  which still return English.

## Routing map

```
/register                          public — Create Company (POST /auth/register)
/login                             public
/                                   protected shell (AppLayout: sidebar + topbar)
  index                             Dashboard (live + executive summary)
  /agents                           Agents (Users) — requires agents.read
  /channels                         Channel configs (Connect WhatsApp, etc.) — channels.read
  /conversations                    Inbox — full filterable/sortable table — conversations.read
  /conversations/:conversationId    Conversation workspace (list + thread/reply/notes/assign + customer panel)
  /customers                        Customer directory (search) — customers.read
  /customers/:customerId            Customer profile — Timeline + ERPNext tabs — customers.read
  /erp-configs                      ERPNext connection setup — erp.manage
  /reports                          Reports hub (tabbed) — reports.read
  /settings/company                 Settings (renamed from "Company Settings") — company.manage (GET has no gate; PATCH does)
  *                                 404 (NotFoundPage), inside the shell so signed-in users keep the sidebar/topbar
*                                   404 (NotFoundPage), signed-out fallback
```

Every gated route wraps its element in `RequirePermission`; the sidebar
independently hides nav entries the current user lacks permission for, so
the two never disagree (both read the same `usePermissions` hook).

## Conversation workspace layout (only the message thread scrolls)

`/conversations/:conversationId` renders `ConversationWorkspacePage.tsx`, a
3-pane layout: a persistent, compact `ConversationListPanel.tsx` on the
left (own status quick-filter, own internal scroll), the existing
`ConversationViewPage.tsx` (message thread + composer + tabs + the
customer info `ConversationSidebar.tsx`) filling the rest, unchanged
internally. Deliberately **not** a replacement for `/conversations`
(`InboxPage.tsx`, unchanged) — that full, filterable/sortable table
(queue mode, mine-only, unassigned-only, the Pick action) stays the
richer triage surface, one click away via the back button; the
workspace's own list is intentionally lighter (a single status
quick-filter, no bulk actions), since its job is fast switching between
conversations without losing the one you have open, not triage.

Responsive: on mobile (`theme.breakpoints.down('md')`) there's no room
for both the list and an open conversation, so only `ConversationViewPage`
shows at this route — `ConversationSidebar`'s existing back button already
returns to `/conversations` (the Inbox, full-width), giving the same
list → detail → back pattern a phone's Mail app uses. No routing change
was needed for this: `ConversationWorkspacePage` simply doesn't render
`ConversationListPanel` when `useMediaQuery` reports non-desktop.

**Making "only the message thread scrolls" actually work required a
one-time, global fix to `AppLayout.tsx`, not just local CSS on this one
page.** Every other page in the app relies on the *whole document*
scrolling (nav sidebar and top bar scroll away with tall content) because
`main`'s `sx` had `flexGrow: 1` but no `minHeight: 0` or `overflow`: a
flex item's automatic minimum size (CSS Flexbox's
`min-height: auto` default) refuses to shrink below its content's
natural height unless overridden, so `main` — and everything above it —
just grew to fit whatever a page rendered, and the browser scrolled the
whole page instead of any one region. `MessageThread.tsx`'s own
`overflowY: 'auto'` (and `ConversationViewPage.tsx`'s own
`minHeight: 0` on its inner `Stack`) were already written assuming a
properly height-bounded ancestor — they just never had one. Adding
`minHeight: 0` to the content column and `minHeight: 0` +
`overflowY: 'auto'` to `main` itself fixes this at the root: `main`
becomes the one scroll container for ordinary pages (visually identical
to before — nav/top bar simply stay pinned now instead of scrolling
away, which is a strict improvement, not a regression), while the
conversation workspace's own subtree, sized to exactly `main`'s
available height with its own `overflow: hidden`, never needs `main`
to grow at all — its list panel, `MessageThread`, and (should a future
page need it) any other region can scroll independently within that
fixed budget.

## Realtime

`features/realtime/RealtimeProvider.tsx` opens exactly one WebSocket
connection per authenticated session, to `${VITE_WS_BASE_URL}/agent`
(default `/api/v1/ws` — see the nginx note in Deployment below for why
that prefix matters), and is mounted once in `AppLayout`, wrapping the
whole shell — never per-conversation, since connecting/disconnecting
this socket flips the caller's agent presence between online/offline on
the backend. It reconnects automatically after a drop (3s delay) and
exposes `sendTyping(conversationId, isTyping)` via `features/realtime/
context.ts`'s `useRealtime()` hook (split into its own file, not
re-exported from `RealtimeProvider.tsx`, to satisfy `react-refresh/
only-export-components` — a file that exports both a component and a
hook breaks Vite's fast refresh).

Inbound `{type: "notification", ...}` frames invalidate the
`features/notifications/` React Query caches (`NOTIFICATIONS_KEY`,
`UNREAD_COUNT_KEY`) so the bell updates live — but those two queries
also poll independently every 30s regardless, since the WebSocket push is
an at-most-once convenience layered on top of `GET /notifications`, never
the only trigger for a refetch (matching the backend's own documented
design in `docs/architecture/notifications.md`). `ReplyBox` sends a
throttled (3s) typing frame on keystroke via the same hook.

## Offline support

Added later (Enterprise Readiness & UX milestone, Priority 2 item 13):
"temporary offline operation with automatic synchronization when
connectivity returns," scoped to what a support agent actually needs
mid-conversation — sending a reply — rather than a full offline-first
rewrite of every read/write path in the app.

- **Detection**: `shared/hooks/useOnlineStatus.ts` reads
  `@tanstack/react-query`'s own `onlineManager` (subscribed to the
  browser's `online`/`offline` events by default) rather than a second,
  independent `navigator.onLine` listener — the same signal that already
  drives React Query's built-in pause/resume behavior, so the UI can
  never show "online" while a paused mutation is still waiting, or vice
  versa. `shared/components/OfflineBanner.tsx` (mounted once in
  `AppLayout`, above the `AppBar`) shows a persistent bar while offline
  and a brief 5s confirmation once back online.
- **Queued sends, same-session**: React Query's *default* `networkMode:
  'online'` for mutations already pauses `useMutation().mutate(...)`
  calls made while offline and automatically retries them the moment
  `onlineManager` reports online again — no custom retry/queue logic
  needed for this part. The only real gap this milestone closes is
  *visibility*: `ReplyBox.tsx` checks `sendMutation.isPaused` to show
  "queued, will send once you're back online" instead of leaving the
  agent guessing whether their message went through, is stuck, or was
  lost.
- **Queued sends, surviving a reload**: a paused mutation is only an
  in-memory JS object — closing the tab or refreshing while offline
  would otherwise lose it. `PersistQueryClientProvider` (wired in
  `AppProviders.tsx`, backed by `app/persister.ts`'s `localStorage`
  persister) persists **only paused mutations**, never query/read-cache
  data (`dehydrateOptions.shouldDehydrateQuery: () => false` — cached
  conversations/customers/messages are never written to `localStorage`,
  both to avoid showing stale data on restore and because that data
  doesn't belong sitting in browser storage). On restore,
  `queryClient.resumePausedMutations()` is called once (`onSuccess` on
  the provider) — restoring only rebuilds the paused mutation in the
  cache, it doesn't retry it itself.
- **The mutationFn problem**: a persisted mutation's *variables* survive
  a reload (they're plain serializable data), but the JS *function* that
  originally ran it doesn't — functions aren't serializable, and the
  component/closure that called `.mutate()` is long gone after a reload.
  `queryClient.setMutationDefaults(key, {mutationFn, onSuccess})`
  registers a real, non-closure function the cache can fall back on when
  no live call site provides one. This only matters for whichever
  mutations are worth surviving a hard reload while queued — currently
  just sending a message (`features/conversations/api.ts`'s
  `SEND_MESSAGE_MUTATION_KEY` / `registerOfflineMutationDefaults`,
  called once at startup in `AppProviders.tsx`). `sendMessage` itself
  takes one combined `{conversationId, payload}` variables object rather
  than two separate arguments specifically so the registered, closure-
  free version has everything it needs from `variables` alone.
- **Deliberately out of scope**: every other mutation (updating a
  conversation's status, transferring it, editing a customer, etc.)
  still gets the free same-session pause/auto-resume behavior above, but
  does **not** survive a hard reload while paused — retrofitting every
  mutation in the app with a `mutationKey` + registered defaults would be
  disproportionate to what "temporary offline operation" actually needs;
  sending a reply is the one action an agent is most likely to be
  mid-way through when connectivity drops. Revisit if another specific
  mutation turns out to need the same reload-survival guarantee.

## Reports

`features/reports/ReportsPage.tsx` is a single tabbed hub (`/reports/:tab?`,
gated by `reports.read`) over the backend's eight report endpoints
(executive, conversations, agent performance, queues, SLA, CSAT, AI usage,
plus an agent-only "My Performance" tab backed by `agent-dashboard`). One
`DateRangeFilter` (native `<input type="date">` fields — deliberately not
`@mui/x-date-pickers`, to avoid a second dependency plus `dayjs` for what
two date inputs already cover) is lifted to the page and shared by every
tab, so switching tabs preserves whatever range is selected; it defaults to
the last 30 days. The "My Performance" tab is hidden unless the current
user's `/auth/me` roles include `"Agent"` — the backend 404s that endpoint
for a caller with no Agent profile (e.g. most Owners/Admins), which
`MyPerformancePanel` also handles gracefully (an `EmptyState`, not an error)
in case a user's roles ever diverge from having an actual Agent record.

Charts use **`@mui/x-charts`** (Community, MIT-licensed, same major version
as `@mui/x-data-grid`) — `BarChart`/`LineChart`/`PieChart`, chosen over a
third-party charting library (Recharts, Nivo, etc.) to stay inside the MUI
theming system already in place rather than introduce a second one.
Report result sets are small, fully-loaded arrays scoped to one date range
(not the paginated `Page<T>` shape `DataTable` wraps), so table panels use
a new `ReportDataGrid` — MUI X Data Grid configured for **client-side**
sorting/pagination, no server round-trip, distinct from `DataTable`'s
server-pagination contract.

**Export**: every date-ranged report except `agent-dashboard` supports
`?export=pdf|xlsx`, returning a binary file instead of JSON.
`ReportExportButtons` downloads it via `apiClient.get(path, {params,
responseType: 'blob'})` (so the request still carries the same
Authorization header as every other API call — a plain `<a href>` to the
API URL couldn't) and triggers the save through a temporary object-URL
`<a download>` element. The export always reflects the full date range,
independent of any client-side-only filter a panel applies to its own
table/chart (e.g. the Conversations tab's channel filter).

**Authenticated blob fetch** is the standing pattern anywhere the app
needs to render bytes from a non-public-read storage bucket as an
`<img>`/download: `apiClient.get(path, {responseType: 'blob'})` +
`URL.createObjectURL(...)`, since a plain `<img src>`/`<a href>` to the
API URL wouldn't carry the Authorization header. First established for
message attachments (`conversations/api.ts`'s `fetchAttachmentBlobUrl`),
reused as-is for the company logo (`company/api.ts`'s
`useCompanyLogoUrl`) rather than inventing a second convention — the only
difference is `useCompanyLogoUrl` wraps it in a React Query hook (keyed
by the logo's storage key, `staleTime`/`gcTime: Infinity`, never
explicitly revoked — a company has one current logo, replaced rarely, so
a handful of stale object URLs left behind over a session is a
negligible cost versus the risk of revoking a blob URL a second still-
mounted consumer is using) since it's read in two places at once
(topbar, Branding settings) rather than fetched once per attachment.

## Reusable UI primitives

`shared/components/` holds the primitives every feature list/detail page
is built from, so no page hand-rolls table pagination, confirm dialogs, or
loading/empty/error states:

- **`DataTable`** — a thin wrapper over **MUI X Data Grid** (Community,
  MIT-licensed, added as a new dependency) configured for server-side
  pagination against this API's `Page<T>` shape (`items`, `total`, `page`,
  `page_size`) — sorting/filtering stay client-disabled by default since
  the backend's list endpoints don't accept generic sort/filter params
  (only the specific query params each endpoint documents), which the
  component makes explicit rather than offering controls that would
  silently no-op. Accepts an optional `error`/`onRetry` pair that renders
  the shared `ErrorState` in place of the grid — every page using
  `DataTable` should wire its list query's error through rather than
  leaving a failed fetch showing an empty grid.
- Agents, Departments, and Customers pages share one search convention:
  a single `search` query param, matched server-side with a case
  insensitive `ilike` across a small set of relevant columns (joining to
  `User` for Agents, since name/email live there, not on `Agent` itself)
  — see `CustomerRepository.list_for_company()` for the reference
  implementation new searchable list endpoints should follow.
- **`FormDialog`** — a generic modal shell (title, form body, submit/
  cancel actions, submit-pending disabling, server-error banner) that
  every Create/Edit dialog (Agent, Channel Config, Customer, ERP Config)
  composes rather than reimplementing.
- **`ConfirmDialog`**, **`EmptyState`**, **`ErrorState`**, **`LoadingState`**
  — used identically across every list/detail page for the
  loading/empty/error trichotomy every React Query-backed view has to
  handle.

## API mocking for tests

`@mswjs/msw` (Mock Service Worker) intercepts at the network layer, so
component tests exercise the real Axios client and real React Query
hooks against realistic HTTP responses instead of mocking `fetch`/hooks
directly. `mocks/handlers/` has one module per feature (`auth.ts`,
`agents.ts`, `channels.ts`, ...), composed into a single `setupServer(...)`
started in `test/setup.ts`. Individual tests override a handler with
`server.use(...)` for error-path cases (validation failures, 403, 409).

## Accessibility

`vitest-axe` runs `axe-core` against rendered output in component tests
for every page-level component — `expect(await axe(container)).toHaveNoViolations()`
alongside the normal RTL assertions, catching missing labels/roles/contrast
issues at the same point a functional regression would be caught, not as a
separate manual pass. MUI's default components are accessible by
construction (labeled form controls, roles on interactive elements,
focus management in dialogs/menus); custom composites (the sidebar nav,
`DataTable` actions, the conversation thread) are where an automated check
earns its keep.

## Testing & quality gates

- `vitest` + `@testing-library/react` (jsdom environment) + `vitest-axe`
  for unit, component, and accessibility assertions; MSW for realistic API
  mocking (see above).
- `eslint` (flat config: `typescript-eslint`, `react-hooks`,
  `react-refresh`, `eslint-config-prettier`), `prettier`, and `tsc --noEmit`
  must all pass before a milestone is committed.
- `test/setup.ts` imports `src/i18n` (same synchronous bootstrap the real
  app uses) and resets `i18n.language` back to `'en'` in `afterEach` —
  i18next is a module-level singleton, so a test that exercises the
  Language setting would otherwise leak its language into every
  subsequent test in the same run. Every existing test's English string
  assertions (`getByText`, `getByRole(..., {name})`, `getByLabelText`)
  keep passing unmodified because every `en.json` value is required to
  be byte-identical to the string it replaced.

## Deployment

Already wired end-to-end (`docker/frontend/Dockerfile`'s `dev` target,
`docker/nginx/Dockerfile`'s multi-stage `frontend-build` → static
`nginx:1.27-alpine` runtime, `docker-compose.yml`/`docker-compose.prod.yml`)
before any feature code existed — the production nginx image builds the
SPA (`npm run build`, `VITE_API_BASE_URL`/`VITE_WS_BASE_URL` baked in as
build args since Vite env vars are compile-time) and serves the static
`dist/` output directly, with `try_files ... /index.html` for
client-side routing and `/api/`, `/metrics` reverse-proxied to the
backend. Each frontend milestone re-verifies `npm run build` still
succeeds against the production Dockerfile target, not just the dev
server.

Both WebSocket routes (the agent realtime gateway, web-chat's per-session
socket) are mounted on the backend under `/api/v1/...`, same as every
REST endpoint — not on a separate top-level prefix — so nginx's one
`/api/` location (with `Upgrade`/`Connection` headers added specifically
for this) proxies them correctly with no special-casing. An earlier
`/ws/` location pointed at a path (`/ws/agent`) that was never actually
registered on the backend and was silently unreachable through nginx the
entire time — see `docs/architecture/event-bus.md`'s incident note.

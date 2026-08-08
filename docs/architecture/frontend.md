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
- **Two ways to set the language, at two different scopes.**
  `company.settings.language` (Settings → Language) is the company-wide
  *default*, the same kind of setting every other Settings tab already
  uses (Branding, Timezone, Business Hours) — it applies to everyone at
  the company who hasn't chosen otherwise for themselves. The AppBar's
  language menu (`AppLayout.tsx`, replacing what used to be a single
  "Translate" icon that only flipped text direction and never actually
  changed the language — a real, reported bug: clicking it showed no
  language options at all, and never applied Arabic translations) is a
  *personal, per-browser* override: any authenticated user, no
  `company.manage` permission needed, since it's a display preference
  for their own session, not a company setting. Selecting a language
  there calls `i18next.changeLanguage(...)` directly and persists the
  choice to `localStorage` (`LANGUAGE_STORAGE_KEY`, `src/i18n/index.ts`)
  — read back as i18next's *initial* `lng` on the next load, the same
  pattern `uiSlice.ts`'s `themeMode`/`direction` already use, so it
  survives a reload without waiting on the company query.
- `useLanguageSync` (`src/i18n/useLanguageSync.ts`, mounted once in
  `AppLayout`) applies the company-wide default whenever
  `company.settings.language` changes, and defaults direction to match
  (`ar` → `rtl`, everything else → `ltr`) — but **only when this browser
  hasn't made its own explicit choice** (`LANGUAGE_STORAGE_KEY` unset).
  A personal AppBar choice always wins over the company default for as
  long as it's set; saving a *new* company default from Settings →
  Language clears the saving admin's own personal override at the same
  time (`LanguageSettingsPanel.tsx`), so the person who just asserted
  "this is our new default" sees their own save actually take effect
  rather than silently continuing to see their old personal choice.
  Only languages with a real translation catalog are offered in either
  picker (`SUPPORTED_I18N_LANGUAGES` in `src/i18n/index.ts`, currently
  `en`/`ar`) — `company/types.ts`'s `SUPPORTED_LANGUAGE` type still lists
  a couple more (kept for backward compatibility with any already-stored
  value) that aren't offered until they have their own catalog.
- Direction (`ltr`/`rtl`) itself remains independent `ui` Redux state —
  selecting a language in the AppBar menu sets both `i18next`'s language
  and this direction default together, in one action, rather than as two
  separate controls a user had to discover independently. Changing it
  flips `document.documentElement[dir]`, swaps the Emotion cache (so
  MUI's `sx`/`styled` output gets RTL-flipped via `stylis-plugin-rtl`),
  and MUI's `theme.direction` is kept in sync so component internals
  (e.g. drawer anchoring) also flip.
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
  index                             Dashboard (live + executive summary) — the one item every signed-in user sees, unlike every route below it
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

The two **operator consoles** sit outside that shell entirely, on their own
chrome (`ConsoleShell`). A platform operator has no company, so `AppLayout`'s
navigation — Inbox, Customers, Reports — would be a dozen links that all 403
for them.

```
/platform                          Platform Console (PlatformRoute → PlatformLayout)
  index                             Companies
  /platform/mail                    Outbound mail settings

/platform/billing                  Billing Console (PlatformRoute → BillingConsoleLayout)
  index                             Revenue dashboard — per currency, no combined total
  /platform/billing/invoices        Invoice management — cross-company search, CSV export, per-document actions
  /platform/billing/payments        Payments, allocations, reversals and refunds
  /platform/billing/ledger          Customer ledger (running balance) + trial balance
  /platform/billing/collections     Aging buckets, who is behind, the dunning sweep
  /platform/billing/companies/:id   One company's billing workspace
  /platform/billing/pricing         Pricing (rates, profiles, models)
  /platform/billing/pricing/companies/:id  One company's pricing
```

The billing console is nested **under** `/platform` rather than mounted at a
new top-level path, so it inherits `PlatformRoute` — a section added here
cannot ship unguarded because somebody forgot the wrapper. `/billing` is the
*tenant's* own billing page and stays theirs.

Its sections are ordered the way a finance day runs rather than
alphabetically: open on the numbers, work through the documents, follow the
money, then chase what did not arrive. Pricing is last because a rate is set
once and read for months.

`features/billingops/` holds the six modules. Two conventions inside it are
worth knowing before editing:

- **`format.ts` is formatting only.** Nothing there adds, subtracts or
  compares amounts — every figure was computed server-side in `Decimal` and
  crosses the wire as a string. How many decimals a currency has is asked of
  `Intl` rather than kept in a map, so the dinar's three places and the
  dollar's two come from ICU rather than from a list that can drift.
- **After any write, invalidate the whole `['billing-ops']` key.** A payment
  moves an invoice's status, the company's standing, the aging report, the
  ledger and the revenue figures at once. A console showing five panels where
  one has caught up is worse than one that briefly shows spinners.

Every gated route wraps its element in `RequirePermission`; the sidebar
independently hides nav entries the current user lacks permission for, so
the two never disagree (both read the same `usePermissions` hook).

Dashboard is the one deliberate exception: `navConfig.ts` declares no
`permission` for it and the route has no `RequirePermission` wrapper,
since it's the universal post-login landing page (`LoginPage.tsx`
defaults `from` to `/`) — every authenticated user needs *some* working
first screen, regardless of their role's permission set. But its only
data source, `GET /reports/live-dashboard`, is gated on `reports.read`,
which a custom role built in Roles & Permissions (chat-only,
knowledge-only) can omit (P6.20's final review: this used to just show
an inline `ErrorState`, a broken-looking first screen for that role).
`DashboardPage.tsx` now checks `hasPermission('reports.read')` itself
and renders a simple "Go to Inbox" landing page instead of firing the
query at all when it's absent — an honest degrade rather than a fake
error.

**Every route is its own chunk (P6.20's final review).** `AppRoutes.tsx`
used to statically `import` all ~20 page components — everything landed
in one entry bundle: `@mui/x-data-grid`, `@mui/x-charts` (+ d3), both
locale bundles, every settings/reports/onboarding screen, measured at
1.9 MB (557 KB gzip). Critically this included the two routes outside
`ProtectedRoute` — `/login` and `/feedback/:conversationId` (the CSAT
survey link emailed straight to end customers) — so a customer tapping
a survey link on their phone downloaded the entire internal agent
console to render a 4.8 KB form. Every page is now `React.lazy(() =>
import(...))`, wrapped in one `<Suspense fallback={<LoadingState />}>`
around the whole `<Routes>` tree — Vite/Rolldown emits each page as its
own chunk automatically; nothing about what's imported changed, only
when. `DataGrid` (~395 KB) and `BarChart` (~267 KB) are now separate
chunks loaded only by the routes that actually render a grid or a chart,
and the main entry chunk dropped to ~345 KB (110 KB gzip) with `/login`
and `/feedback` now each under 5 KB of their own code.

## Conversation workspace layout (only the panes scroll)

`/conversations` and `/conversations/:conversationId` render the **same**
component, `InboxWorkspace.tsx`: the conversation list on the left, the
open conversation (`ConversationViewPage.tsx`) on the right. The id in
the URL selects which conversation the right pane shows; it does not
select a different screen.

That is the correction to the design this replaces, where opening a
conversation navigated to a separate page. An agent working a queue did
list → conversation → Back → list on every item, losing their scroll
position and their chosen queue each time. Now the list keeps both, and
marks the selected row with `aria-current`.

Inside the right pane, top to bottom:

- `ConversationHeaderBar.tsx` — who, what state, the SLA band, the
  ticking durations, and every ownership action (Pick up, Ask AI, Take
  over, Transfer, Release). Fixed; `flexShrink: 0`.
- Tabs — Messages / Internal notes / Transfers. Fixed.
- `MessageThread.tsx` — the only region that scrolls.
- `ReplyBox.tsx` — the composer, including the saved-reply picker.
  Fixed.
- `ConversationSidebar.tsx` — in a right-anchored `Drawer`, opened from
  the header's (i). Status, queue, customer, channel, AI summary. It
  overlays rather than reflowing, so opening it never resizes the thread.

Ownership actions are in the header and *nowhere else*; status and queue
are in the drawer and nowhere else. The split is replying versus
re-filing, and nothing appears in both places.

Responsive: below MUI's `md`, `InboxWorkspace` renders one pane at a
time — the list, or the conversation with a back arrow. Stock `md` is
the right breakpoint here because the workspace no longer carries a
third fixed column: the customer details became an overlay drawer, so
the only fixed chrome is the app nav and the 380px list pane, leaving
the thread a genuine working width at 900px.

1280/820px: the page never scrolls, every column reports its own scroll
region, and the composer stays put while the thread scrolls. The harness
lives in `frontend/.visual-check/` — CSS reasoning alone had previously
declared this fixed twice when it was not.

**Independent per-column scrolling is a product-wide requirement, not a
conversation-page detail (2026-07-28).** Any page showing multiple
panels side by side must behave like an enterprise workspace
(Intercom/Zendesk), never like a long document:

- **The page itself must not scroll vertically.** Each column owns its
  own scroll region; there is no outer scrollbar that can move the whole
  layout. Concretely: the route is rendered full-bleed (`AppLayout`'s
  `main` drops its `p: 3` gutter *and* switches `overflowY` to `hidden`
  for such routes — see `isFullBleedRoute`), and the page fills the
  remaining height with `flexGrow: 1` + `minHeight: 0`.
- **Every column is `flexGrow: 1; minHeight: 0; overflowY: auto` inside a
  height-bounded parent.** `minHeight: 0` is the non-obvious half: a flex
  item's automatic minimum size otherwise refuses to shrink below its
  content, so the column grows the page instead of scrolling itself.
- **Fixed chrome is `flexShrink: 0`** — filter tabs, the workspace header
  bar, the composer. Without a declared floor, flexbox is free to squeeze
  them when a sibling grows.
- **Scrolling one column must never move another.** This falls out of the
  two rules above: no shared scroll ancestor exists to propagate.

The conversation workspace is the reference implementation:
`InboxWorkspace` (list pane | conversation), and inside it
`ConversationViewPage` (fixed header bar and tabs, then the thread and
the composer). The list pane's queue chips and heading are fixed while
its rows scroll; `MessageThread` scrolls while `ReplyBox` stays put; the
details drawer scrolls independently. Opening a conversation always lands on the newest message —
`MessageThread` re-arms its stick-to-bottom ref on every
`conversationId` change, because that ref intentionally survives
re-renders and the component's prop changes rather than it remounting
when the agent switches conversations.

**`main` is a flex column, so a fill-height page can survive the setup
banner (fixed 2026-07-28).** The height chain above still had one hole:
`main` was a *block* container, and `ConversationWorkspacePage` sized
itself with `height: 100%`. That percentage resolves against `main`'s
whole content box and cannot know about a sibling — so whenever the
"finish setting up your company" banner rendered above `<Outlet/>`
(`showSetupBanner`: an owner/admin with incomplete onboarding, on every
route), banner height + 100% exceeded the available space, `main`
scrolled, and the entire conversation row moved instead of just the
message thread. Reported as "scrolling still moves the row, not only the
messages."

`main` is now `display: flex; flexDirection: column`, the banner is
`flexShrink: 0`, and the workspace asks for `flexGrow: 1` + `minHeight: 0`
instead of `height: 100%` — it gets exactly what's left, banner or no
banner, with no percentage arithmetic to get wrong. Ordinary pages are
unaffected: their top-level elements simply become column flex items,
which stack the same way block children did.

**The composer's "always visible" contract, and one shared card for
both panes (2026-07-28).** Two follow-ons the scroll work above did not
cover — its scope was `MessageThread`'s scroll isolation, not the
composer or the pane framing:

- `ReplyBox` had **no `flexShrink: 0`**. It stayed at the bottom only
  incidentally: it's the last child of a `minHeight: 0` flex column
  whose only growing sibling (`MessageThread`) absorbs the slack. That
  works right up until the composer itself grows — stacked send/upload
  error `Alert`s, attachment chips, a multi-line draft — at which point
  flexbox is free to shrink it, since nothing declared a floor.
  `flexShrink: 0` (plus an explicit `bgcolor: 'background.paper'`) makes
  "you never lose access to the composer while scrolling history" an
  actual layout contract. Deliberately *not* `position: sticky/fixed`:
  the column is already height-bounded, so the composer is on-screen by
  construction — sticky would add z-index/backdrop concerns for no gain.
  `ConversationViewPage.test.tsx` asserts the `flexShrink` directly.
  `src/test/viewport.ts` installs the `matchMedia` jsdom lacks, defaulting
  to a 1280px laptop — without it every `useMediaQuery` reads false and
  the two-pane layout could never be exercised by a test at all.
- The message column and the sidebar each drew **their own borders**
  inside a separately-bordered rounded card, so the sidebar read as a
  mismatched sub-panel bolted onto the conversation rather than the same
  card's second column. The divider is now declared once on the shared
  row (`& > *:not(:first-of-type)`), the row gets `overflow: hidden` so
  both panes clip to its rounded corners (a descendant's own
  `overflowY: auto` still scrolls normally — only corners are affected),
  and the sidebar wrapper carries the fixed `280px` width and a
  `bgcolor: 'action.hover'` so the two panes read as one deliberate
  two-column card. The wrapper must remain `ConversationSidebar`'s
  *immediate* DOM parent with `overflowY: 'auto'` — an existing test
  pins that.

**"Always jumps to the latest message" (fixed 2026-07-28).**
`MessageThread`'s scroll-to-bottom effect fired unconditionally any
time the newest message's id changed — a genuine new message (the
customer's next one, an agent's own reply from another tab, an
Autopilot auto-reply), not a background poll or "load older" — but with
no check for whether the reader was already at the bottom first. An
agent scrolled up mid-history got yanked back to the newest message the
instant *any* new message arrived, with no way to keep reading. Fixed
by tracking "was I within `STICK_TO_BOTTOM_THRESHOLD_PX` (48px) of the
bottom" in a ref, updated on the scroll container's own `onScroll`
(not React state, so reading it never itself triggers a render) — the
auto-scroll effect now only fires when that ref says true at the moment
a new message arrives. This is the same "stick to bottom" pattern every
mainstream chat UI uses: autoscroll while caught up, stop the moment you
scroll away to read something older.

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

## Inbox as the design standard (Beta 4)

`InboxPage.tsx`/`ConversationCells.tsx` is the reference implementation
for how a dense, triage-oriented list page should look and behave in
this app — future list pages that need to convey priority/urgency at a
glance should follow its patterns rather than inventing new ones:

- **One glance, one column.** Identity and unread state share a single
  cell (`CustomerIdentityCell`): an avatar with an anchored unread-count
  badge, not a separate "unread" column — an agent's eye checks one
  place, not several, to see "is there something new here."
- **Silence is the default state.** `PriorityBadge` renders nothing for
  `normal` priority (the common case) and `SlaIndicator` renders nothing
  when a conversation is on-track — badges only appear for genuine
  deviations (`high`/`urgent`, "approaching SLA," "breached"), so the
  signal stands out instead of competing with a badge on every row. Don't
  add a badge/chip for a row's default state "for consistency"; only
  surface what needs attention.
- **Recognizable-at-a-glance channel identity, plus which channel it
  was.** `ChannelIcon` maps each channel type to a brand-colored icon in
  a tinted circular badge (`CHANNEL_ICONS` in `ConversationCells.tsx`) —
  faster to scan than reading "WhatsApp Business" in a column. The badge
  alone was the whole column through Beta 5, which is where the
  pattern's limit showed: a company routinely runs several channels of
  one type
  (two WhatsApp numbers, a support and a sales inbox), and no brand mark
  can distinguish them. `ChannelCell` now pairs the icon with the
  channel's `display_name`, so the icon answers "what kind" and the label
  answers "which one." The general rule: an icon may replace a *type*
  label, never an *instance* name. An id the channel list can't resolve
  (channels are soft-deleted and keep their conversations) renders a
  labelled "Unknown channel" placeholder rather than a bare icon.
- **Deterministic avatar color.** Customer avatars derive their
  background color from a hash of the customer's name
  (`avatarColorFor`), so the same customer always renders the same color
  across pages/sessions without needing a dedicated backend field.
  Reuse this helper rather than inventing a new avatar-coloring scheme
  elsewhere.
- **Every `DataTable` wires `error`/`onRetry`.** `InboxPage` previously
  left the grid's `error`/`onRetry` props unset, so a failed fetch
  silently rendered an empty grid instead of the shared `ErrorState` —
  fixed in Beta 4. Every new `DataTable` usage should wire both from the
  start; `DepartmentsPage.tsx` is the reference for the pattern.
- **Keyboard efficiency is additive, never a reimplementation.** The
  Inbox's `j`/`k` row navigation (Gmail-style, moves focus to the next/
  previous row at the currently-focused column) is layered on top of
  **MUI X Data Grid's own native ArrowUp/ArrowDown/Enter cell-focus
  handling**, left completely alone — a page should never reimplement
  arrow-key/Enter navigation the grid already provides correctly.

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

**Popover, not Menu, for compound popup content (P6.20's final
review).** MUI's `Menu` renders `role="menu"` on its list, which requires
every direct child to be a `menuitem` — `AppLayout.tsx`'s account menu
(user-info block + availability `ToggleButtonGroup`) and
`NotificationBell.tsx`'s notification menu ("Mark all read" header,
"View all" footer) both used to put non-`menuitem` content directly
inside that list, which axe correctly flags as
`aria-required-children` at critical impact, and which menu-mode
arrow-key navigation silently skips over entirely (a screen-reader user
opening the account menu would never reach the availability picker at
all). Both now use `Popover` + `MenuList` instead: `Popover` carries no
`role="menu"` list semantics, so it can host arbitrary content, while
the actual actions still sit inside a `MenuList` for unchanged keyboard
behavior. Neither component's tests previously opened the menu and ran
axe on it (only the closed state) — both now do.

Message bubbles (`MessageThread.tsx`) previously conveyed sender
(customer vs. agent) only through side-of-thread alignment and
background color — a WCAG 1.4.1 (Use of Color) failure axe can't catch,
since the markup is technically valid. Each bubble now renders a small
visible "You"/"Customer" caption above the body text.

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


## Conversation details are on demand, not a column

The customer/conversation details panel was originally a permanent fifth
column in the conversation workspace. It is now an overlay opened from
the conversation header's ⋮ menu ("Conversation details").

The reason is the width budget. At 1440px the workspace spends 200px on
the app nav, 220px on filters and 320px on the conversation list before
the chat gets anything; a permanent 280px details column left the
message thread 420px — narrower than the list beside it — for
information an agent consults occasionally rather than continuously.
Removing it gives the thread the full 700px.

It is a **temporary right-anchored `Drawer`**, not a collapsible column,
and that distinction is the requirement: an overlay does not reflow the
chat, so opening and closing details never resizes or re-wraps the
message thread. Verified in a real browser — the chat column measures
700px with the panel closed, open, and closed again.

`keepMounted` is set so the panel's queries aren't re-issued on every
open, and the panel scrolls inside its own bounded region like every
other column here (see "Independent per-column scrolling").

The workspace's minimum-width threshold no longer counts the details
panel, so the filters and list panes survive at widths that previously
dropped them.

Tests that assert on details-panel controls must open it first, which is
what `openDetails()` in `ConversationViewPage.test.tsx` does — tests
about the composer deliberately do **not**, since the composer sits
behind the overlay and cannot be typed into while it is open.

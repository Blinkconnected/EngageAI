# Navigation Information Architecture — Proposal

**Status:** proposal. Not implemented.
**Trigger:** the left menu is a flat list of seventeen unrelated items.
**Scope:** `navConfig.ts` and the sidebar component. No routing,
permission or backend changes.

---

## 1. The problem

`frontend/src/features/layout/navConfig.ts` renders every destination as
a peer:

```
Dashboard   Inbox      Customers   Agents      Departments
Channels    Status     Services    Queues      Roles
SLA         Intelligence  Reports  Billing     ERPNext
Settings
```

Seventeen entries, no grouping, ordered by the milestone that added them.
The file says so:

> *"The sidebar grows feature-by-feature alongside the roadmap — an entry
> is added here in the same milestone its route/page is built."*

That rule is good for correctness — no item ever points at an unbuilt
page — and it is why the ordering carries no meaning. Growth order is not
information architecture.

### Why it costs something

**These are not the same kind of thing.**

| Kind | Items | Used |
|---|---|---|
| Daily work | Inbox, Customers, Dashboard | Constantly |
| Analysis | Reports, Intelligence, Billing | Weekly |
| Organisation setup | Agents, Departments, Roles | Once, then rarely |
| Routing setup | Services, Queues, SLA | Once, then rarely |
| Connections | Channels, Status, ERPNext | At setup, then on failure |
| Everything else | Settings | Rarely |

An agent uses two of seventeen items all day and scans past fifteen they
will never open. An administrator setting up a workspace gets no hint
which items must be configured before the platform will route anything —
they are told there are seventeen things and left to infer the order.

**Two concrete symptoms:**

- **Services and Queues share an icon** (`AltRouteOutlinedIcon`). That is
  an accurate signal — they are two halves of one idea — expressed as a
  collision rather than as structure.
- **Status sits between Channels and Services**, adjacent to Channels by
  accident of insertion order rather than by design, even though it is
  the natural companion to it.

## 2. Proposed structure

Six groups. Collapsed by default except the first.

```
  ● Dashboard

  WORK
    Inbox
    Customers

  INSIGHTS
    Reports
    Intelligence

  ROUTING
    Services
    Queues
    SLA

  CONNECTIONS
    Channels
    Status
    ERPNext

  ORGANISATION
    Agents
    Departments
    Roles

  ● Settings
  ● Billing
```

**Dashboard, Settings and Billing stay top-level.** Dashboard is the
landing page; Settings is the conventional last item; Billing is a
distinct commercial concern that does not belong under Insights (it is
not analysis) or Organisation (it is not people).

### Why these groups

| Group | Answers |
|---|---|
| **Work** | What am I doing right now |
| **Insights** | How are we doing |
| **Routing** | Where does work go |
| **Connections** | How do customers reach us |
| **Organisation** | Who works here |

Each group answers one question. That is the test a group has to pass —
if a group needs "and" to describe it, it is two groups.

### Placement decisions worth stating

**Status under Connections, not Insights.** It reports on channel health,
and the person checking it is the person who owns the channel connection.
Health belongs beside the thing it describes.

**Intelligence under Insights, not Settings.** It answers "what is the
platform noticing", which is a reporting question. The current code
already argues this in a comment; the proposal keeps that reasoning and
gives it a group to live in.

**SLA under Routing, not Settings.** SLA targets are resolved through the
Service → Queue chain. Putting SLA beside Services and Queues shows the
chain in the navigation instead of leaving it to be learned.

**Roles under Organisation, not Settings.** Roles are about people. An
administrator adding an agent and assigning a role should not cross the
menu to do it.

## 3. Behaviour

| Rule | Reason |
|---|---|
| A group renders only if the user can see ≥ 1 child | Empty group headers are worse than a flat list |
| A group with exactly 1 visible child renders that child flat | A disclosure triangle hiding one item is friction with no payoff |
| The group containing the active route is expanded | Never hide where the user is |
| Expansion state persists per user | Administrators live in different groups than agents |
| Group headers are labels, not links | Nothing to click that goes nowhere |

The first two rules matter most. Permissions and feature flags already
hide items, so a restricted agent might see only Inbox and Customers —
and must not be shown four empty headers as evidence of what they cannot
access.

## 4. What this does not change

- **No route changes.** Every path stays as it is; bookmarks survive.
- **No permission changes.** The same `permission`, `requiresFeature` and
  `requiresErpEnabled` filters apply, per item.
- **No backend changes.**
- **No new dependencies.** MUI already provides `Collapse` and `List`.

## 5. Implementation sketch

`NavItem` gains an optional group; a `NAV_GROUPS` array gives order and
labels:

```ts
export interface NavItem {
  label: string
  path: string
  icon: ComponentType<...>
  permission?: string
  requiresFeature?: string
  requiresErpEnabled?: boolean
  matchPath?: string
  group?: NavGroupKey          // absent = top level
}

export const NAV_GROUPS = [
  { key: 'work',         label: 'SideNav.groupWork' },
  { key: 'insights',     label: 'SideNav.groupInsights' },
  { key: 'routing',      label: 'SideNav.groupRouting' },
  { key: 'connections',  label: 'SideNav.groupConnections' },
  { key: 'organisation', label: 'SideNav.groupOrganisation' },
] as const
```

The sidebar groups items by `group`, applies the existing visibility
filter **before** deciding whether a group renders, and collapses the
rest.

**Group labels are i18n keys**, like every other label — six new strings
in the `layout` namespace for both `en` and `ar`.

**Give Services and Queues distinct icons** while touching this file.
Sharing one is the clearest evidence the grouping is overdue, and it
stops being harmless once they sit adjacent under a shared header.

## 6. Effort

| Item | Estimate |
|---|---|
| `navConfig.ts` restructure | 1 hour |
| Collapsible group rendering | 2 hours |
| Visibility rules (§3) | 1 hour |
| Persist expansion state | 1 hour |
| i18n strings, en + ar | 30 min |
| Two icons | 15 min |
| Tests | 2 hours |
| **Total** | **~1 day** |

## 7. Verification

1. An agent with only conversation permissions sees **Work** and nothing
   else — no empty headers.
2. A user whose plan excludes ERP and SLA sees **Connections** with two
   items and **Routing** with two.
3. Deep-linking to `/reports/performance` expands **Insights** and
   highlights Reports.
4. Expansion survives a reload.
5. RTL layout is correct in Arabic — group headers and indentation mirror.

## 8. Alternatives considered

**Leave it flat.** Defensible at ten items; seventeen is past it, and the
list only grows.

**Two-level flyout menus.** More powerful, worse on touch and RTL, and it
hides structure behind hover. Rejected.

**Search-first navigation (command palette).** Genuinely good for power
users and no help to an administrator who does not yet know what the
platform is called. Worth adding *later*, as a complement rather than a
replacement.

**Role-based menus** — show administrators a different menu from agents.
Rejected: permissions already do this, and a second mechanism deciding
visibility would mean two places to look when somebody cannot find a
screen.

---

## See also

- [TD-5](../releases/v1.0-technical-debt.md#td-5) — the register entry
- [User Guide](../guides/user-guide.md#2-finding-your-way-around)
- `frontend/src/features/layout/navConfig.ts`

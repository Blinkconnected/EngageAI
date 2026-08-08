import type { ComponentType } from 'react'
import DashboardOutlinedIcon from '@mui/icons-material/DashboardOutlined'
import HubOutlinedIcon from '@mui/icons-material/HubOutlined'
import GroupOutlinedIcon from '@mui/icons-material/GroupOutlined'
import ApartmentOutlinedIcon from '@mui/icons-material/ApartmentOutlined'
import BusinessOutlinedIcon from '@mui/icons-material/BusinessOutlined'
import HelpOutlineOutlinedIcon from '@mui/icons-material/HelpOutlineOutlined'
import ForumOutlinedIcon from '@mui/icons-material/ForumOutlined'
import InboxOutlinedIcon from '@mui/icons-material/InboxOutlined'
import ContactsOutlinedIcon from '@mui/icons-material/ContactsOutlined'
import SyncOutlinedIcon from '@mui/icons-material/SyncOutlined'
import AssessmentOutlinedIcon from '@mui/icons-material/AssessmentOutlined'
import ReceiptLongOutlinedIcon from '@mui/icons-material/ReceiptLongOutlined'
import AltRouteOutlinedIcon from '@mui/icons-material/AltRouteOutlined'
import FormatListNumberedOutlinedIcon from '@mui/icons-material/FormatListNumberedOutlined'
import AdminPanelSettingsOutlinedIcon from '@mui/icons-material/AdminPanelSettingsOutlined'
import RuleOutlinedIcon from '@mui/icons-material/RuleOutlined'
import MonitorHeartOutlinedIcon from '@mui/icons-material/MonitorHeartOutlined'

/** The groups the sidebar renders, in order.
 *
 * The sidebar grew one entry per milestone, which is the right rule for
 * correctness — an item is never added before the page it points at — and
 * the reason the ordering carried no meaning. Seventeen flat entries mixed
 * work somebody does hourly with configuration they touch once, and an
 * administrator had no way to tell which was which.
 *
 * Each group answers exactly one question. That is the test for adding
 * one: if it needs "and" to describe it, it is two groups.
 */
export const NAV_GROUPS = [
  { key: 'work', label: 'SideNav.groupWork' },
  { key: 'insights', label: 'SideNav.groupInsights' },
  { key: 'routing', label: 'SideNav.groupRouting' },
  { key: 'connections', label: 'SideNav.groupConnections' },
  { key: 'organisation', label: 'SideNav.groupOrganisation' },
] as const

export type NavGroupKey = (typeof NAV_GROUPS)[number]['key']

export interface NavItem {
  /** An i18next key (`t(item.label)` in SideNav.tsx), not literal display
   * text — namespace "layout", e.g. "SideNav.navDashboard". */
  label: string
  path: string
  icon: ComponentType<{ fontSize?: 'small' | 'medium' | 'large' | 'inherit' }>
  /** Permission required to see this item; omit for "any authenticated user". */
  permission?: string
  /** Also requires the company to have ERP enabled (see
   * docs/architecture/company-onboarding.md) — completely hidden
   * otherwise, not just permission-gated. */
  requiresErpEnabled?: boolean
  /** Product feature this item needs — hidden entirely when the
   * company's plan doesn't include it (see docs/architecture/billing.md).
   * Distinct from `permission`: that asks whether the *user* may, this
   * asks whether the *company* bought it. */
  requiresFeature?: string
  /** Section root used for sidebar active-highlighting, when it differs
   * from `path` itself — needed only for an item whose `path` embeds a
   * default tab (e.g. `/reports/executive`), so any OTHER tab under the
   * same section (`/reports/performance`) still highlights this item.
   * Defaults to `path` when omitted. */
  matchPath?: string
  /** Which group this item belongs under. Omit for a top-level entry —
   * Dashboard, Billing and Settings stay flat because each is a
   * destination in its own right rather than one of several related
   * screens. */
  group?: NavGroupKey
}

/**
 * The sidebar grows feature-by-feature alongside the roadmap — an entry is
 * added here in the same milestone its route/page is built, never ahead of
 * it, so there is never a nav item pointing at an unbuilt page.
 */
export const NAV_ITEMS: NavItem[] = [
  { label: 'SideNav.navDashboard', path: '/', icon: DashboardOutlinedIcon },
  {
    label: 'SideNav.navInbox',
    path: '/conversations',
    group: 'work',
    icon: InboxOutlinedIcon,
    permission: 'conversations.read',
  },
  {
    label: 'SideNav.navCustomers',
    path: '/customers',
    group: 'work',
    icon: ContactsOutlinedIcon,
    permission: 'customers.read',
  },
  {
    label: 'SideNav.navAgents',
    path: '/agents',
    group: 'organisation',
    icon: GroupOutlinedIcon,
    permission: 'agents.read',
  },
  {
    label: 'SideNav.navDepartments',
    path: '/departments',
    group: 'organisation',
    icon: ApartmentOutlinedIcon,
    permission: 'departments.read',
  },
  {
    label: 'SideNav.navChannels',
    path: '/channels',
    group: 'connections',
    icon: ForumOutlinedIcon,
    permission: 'channels.read',
  },
  {
    label: 'SideNav.navStatus',
    path: '/status',
    group: 'connections',
    icon: MonitorHeartOutlinedIcon,
    permission: 'channels.read',
  },
  {
    label: 'SideNav.navServices',
    path: '/services',
    group: 'routing',
    icon: AltRouteOutlinedIcon,
    permission: 'queues.read',
  },
  {
    label: 'SideNav.navQueues',
    // A different icon from Services. They shared one, which was an
    // accurate signal that they belong together — but once they sit
    // adjacent under a shared heading it stops being harmless and just
    // makes two rows look like a rendering mistake.
    path: '/queues',
    group: 'routing',
    icon: FormatListNumberedOutlinedIcon,
    permission: 'queues.read',
  },
  {
    label: 'SideNav.navRolesPermissions',
    path: '/roles',
    group: 'organisation',
    icon: AdminPanelSettingsOutlinedIcon,
    permission: 'roles.manage',
  },
  {
    label: 'SideNav.navSlaBuilder',
    path: '/sla',
    group: 'routing',
    icon: RuleOutlinedIcon,
    permission: 'sla_policies.read',
    requiresFeature: 'sla',
  },
  {
    // Beside Reports rather than under Settings: it answers "what is the
    // platform noticing", which is a reporting question, not a
    // configuration one — even though it carries one dial.
    label: 'SideNav.navIntelligence',
    path: '/intelligence',
    group: 'insights',
    icon: HubOutlinedIcon,
    permission: 'intelligence.read',
  },
  {
    label: 'SideNav.navReports',
    path: '/reports/executive',
    group: 'insights',
    matchPath: '/reports',
    icon: AssessmentOutlinedIcon,
    permission: 'reports.read',
  },
  {
    label: 'SideNav.navBilling',
    path: '/billing',
    icon: ReceiptLongOutlinedIcon,
    permission: 'billing.read',
  },
  {
    label: 'SideNav.navErpNext',
    path: '/erp-configs',
    group: 'connections',
    icon: SyncOutlinedIcon,
    permission: 'erp.manage',
    requiresErpEnabled: true,
    requiresFeature: 'erp',
  },
  {
    label: 'SideNav.navSettings',
    path: '/settings/company/general',
    matchPath: '/settings/company',
    icon: BusinessOutlinedIcon,
    permission: 'company.manage',
  },
  {
    // Top level and last, with no permission: everybody who can sign in
    // can be stuck, and help gated behind a role is help the person who
    // needs it most cannot reach.
    label: 'SideNav.navGuide',
    path: '/help',
    icon: HelpOutlineOutlinedIcon,
  },
]

import type { ComponentType } from 'react'
import DashboardOutlinedIcon from '@mui/icons-material/DashboardOutlined'
import GroupOutlinedIcon from '@mui/icons-material/GroupOutlined'
import ApartmentOutlinedIcon from '@mui/icons-material/ApartmentOutlined'
import BusinessOutlinedIcon from '@mui/icons-material/BusinessOutlined'
import ForumOutlinedIcon from '@mui/icons-material/ForumOutlined'
import InboxOutlinedIcon from '@mui/icons-material/InboxOutlined'
import ContactsOutlinedIcon from '@mui/icons-material/ContactsOutlined'
import SyncOutlinedIcon from '@mui/icons-material/SyncOutlined'
import AssessmentOutlinedIcon from '@mui/icons-material/AssessmentOutlined'
import ReceiptLongOutlinedIcon from '@mui/icons-material/ReceiptLongOutlined'
import AltRouteOutlinedIcon from '@mui/icons-material/AltRouteOutlined'
import AdminPanelSettingsOutlinedIcon from '@mui/icons-material/AdminPanelSettingsOutlined'
import RuleOutlinedIcon from '@mui/icons-material/RuleOutlined'
import MonitorHeartOutlinedIcon from '@mui/icons-material/MonitorHeartOutlined'

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
    icon: InboxOutlinedIcon,
    permission: 'conversations.read',
  },
  {
    label: 'SideNav.navCustomers',
    path: '/customers',
    icon: ContactsOutlinedIcon,
    permission: 'customers.read',
  },
  {
    label: 'SideNav.navAgents',
    path: '/agents',
    icon: GroupOutlinedIcon,
    permission: 'agents.read',
  },
  {
    label: 'SideNav.navDepartments',
    path: '/departments',
    icon: ApartmentOutlinedIcon,
    permission: 'departments.read',
  },
  {
    label: 'SideNav.navChannels',
    path: '/channels',
    icon: ForumOutlinedIcon,
    permission: 'channels.read',
  },
  {
    label: 'SideNav.navStatus',
    path: '/status',
    icon: MonitorHeartOutlinedIcon,
    permission: 'channels.read',
  },
  {
    label: 'SideNav.navQueues',
    path: '/queues',
    icon: AltRouteOutlinedIcon,
    permission: 'queues.read',
  },
  {
    label: 'SideNav.navRolesPermissions',
    path: '/roles',
    icon: AdminPanelSettingsOutlinedIcon,
    permission: 'roles.manage',
  },
  {
    label: 'SideNav.navSlaBuilder',
    path: '/sla',
    icon: RuleOutlinedIcon,
    permission: 'sla_policies.read',
    requiresFeature: 'sla',
  },
  {
    label: 'SideNav.navReports',
    path: '/reports/executive',
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
]

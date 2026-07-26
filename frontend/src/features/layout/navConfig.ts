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
import NewReleasesOutlinedIcon from '@mui/icons-material/NewReleasesOutlined'

export interface NavItem {
  label: string
  path: string
  icon: ComponentType<{ fontSize?: 'small' | 'medium' | 'large' | 'inherit' }>
  /** Permission required to see this item; omit for "any authenticated user". */
  permission?: string
  /** Also requires the company to have ERP enabled (see
   * docs/architecture/company-onboarding.md) — completely hidden
   * otherwise, not just permission-gated. */
  requiresErpEnabled?: boolean
}

/**
 * The sidebar grows feature-by-feature alongside the roadmap — an entry is
 * added here in the same milestone its route/page is built, never ahead of
 * it, so there is never a nav item pointing at an unbuilt page.
 */
export const NAV_ITEMS: NavItem[] = [
  { label: 'Dashboard', path: '/', icon: DashboardOutlinedIcon },
  {
    label: 'Inbox',
    path: '/conversations',
    icon: InboxOutlinedIcon,
    permission: 'conversations.read',
  },
  {
    label: 'Customers',
    path: '/customers',
    icon: ContactsOutlinedIcon,
    permission: 'customers.read',
  },
  { label: 'Agents', path: '/agents', icon: GroupOutlinedIcon, permission: 'agents.read' },
  {
    label: 'Departments',
    path: '/departments',
    icon: ApartmentOutlinedIcon,
    permission: 'departments.read',
  },
  { label: 'Channels', path: '/channels', icon: ForumOutlinedIcon, permission: 'channels.read' },
  {
    label: 'Reports',
    path: '/reports/executive',
    icon: AssessmentOutlinedIcon,
    permission: 'reports.read',
  },
  {
    label: 'ERPNext',
    path: '/erp-configs',
    icon: SyncOutlinedIcon,
    permission: 'erp.manage',
    requiresErpEnabled: true,
  },
  // No `permission` — release/version info isn't sensitive (the backend
  // doesn't even require authentication for it) — every authenticated
  // user sees this, like `Dashboard` at the top of this list.
  { label: 'Changelog', path: '/changelog', icon: NewReleasesOutlinedIcon },
  {
    label: 'Company settings',
    path: '/settings/company/general',
    icon: BusinessOutlinedIcon,
    permission: 'company.manage',
  },
]

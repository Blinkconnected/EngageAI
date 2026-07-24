import type { ComponentType } from 'react'
import DashboardOutlinedIcon from '@mui/icons-material/DashboardOutlined'
import GroupOutlinedIcon from '@mui/icons-material/GroupOutlined'
import BusinessOutlinedIcon from '@mui/icons-material/BusinessOutlined'
import ForumOutlinedIcon from '@mui/icons-material/ForumOutlined'
import InboxOutlinedIcon from '@mui/icons-material/InboxOutlined'

export interface NavItem {
  label: string
  path: string
  icon: ComponentType<{ fontSize?: 'small' | 'medium' | 'large' | 'inherit' }>
  /** Permission required to see this item; omit for "any authenticated user". */
  permission?: string
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
  { label: 'Agents', path: '/agents', icon: GroupOutlinedIcon, permission: 'agents.read' },
  { label: 'Channels', path: '/channels', icon: ForumOutlinedIcon, permission: 'channels.read' },
  {
    label: 'Company settings',
    path: '/settings/company',
    icon: BusinessOutlinedIcon,
    permission: 'company.manage',
  },
]

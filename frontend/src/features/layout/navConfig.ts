import type { ComponentType } from 'react'
import DashboardOutlinedIcon from '@mui/icons-material/DashboardOutlined'

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
export const NAV_ITEMS: NavItem[] = [{ label: 'Dashboard', path: '/', icon: DashboardOutlinedIcon }]

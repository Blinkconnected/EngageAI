import { Box, List, ListItemButton, ListItemIcon, ListItemText, Toolbar } from '@mui/material'
import { NavLink, matchPath, useLocation } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useAppSelector } from '../../app/hooks'
import { usePermissions } from '../../shared/hooks/usePermissions'
import { useIsErpEnabled } from '../company/api'
import logoLight from '../../assets/logo-light.png'
import logoDark from '../../assets/logo-dark.png'
import { NAV_ITEMS } from './navConfig'

export function SideNav({ onNavigate }: { onNavigate?: () => void }) {
  const { t } = useTranslation('layout')
  const { hasPermission } = usePermissions()
  const location = useLocation()
  const isErpEnabled = useIsErpEnabled()
  const themeMode = useAppSelector((state) => state.ui.themeMode)

  const visibleItems = NAV_ITEMS.filter(
    (item) =>
      (!item.permission || hasPermission(item.permission)) &&
      (!item.requiresErpEnabled || isErpEnabled),
  )

  return (
    <>
      <Toolbar>
        <Box
          component="img"
          src={themeMode === 'dark' ? logoDark : logoLight}
          alt={t('SideNav.logoAlt')}
          sx={{ height: 28, width: 'auto' }}
        />
      </Toolbar>
      <List component="nav" aria-label={t('SideNav.mainNavigationAriaLabel')} sx={{ px: 1 }}>
        {visibleItems.map((item) => {
          // Prefix match (not exact equality) so a nested/detail route —
          // a conversation, a customer profile, a non-default Settings/
          // Reports tab — keeps its section highlighted instead of
          // going blank. `end: true` only for the root Dashboard item,
          // or it would match every path.
          const sectionPath = item.matchPath ?? item.path
          const selected =
            matchPath({ path: sectionPath, end: sectionPath === '/' }, location.pathname) != null
          const Icon = item.icon
          return (
            <ListItemButton
              key={item.path}
              component={NavLink}
              to={item.path}
              selected={selected}
              onClick={onNavigate}
              sx={{ borderRadius: 2, mb: 0.5 }}
            >
              <ListItemIcon sx={{ minWidth: 40 }}>
                <Icon fontSize="small" />
              </ListItemIcon>
              <ListItemText primary={t(item.label)} />
            </ListItemButton>
          )
        })}
      </List>
    </>
  )
}

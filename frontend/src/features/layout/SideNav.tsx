import { Box, List, ListItemButton, ListItemIcon, ListItemText, Toolbar } from '@mui/material'
import { NavLink, useLocation } from 'react-router-dom'
import { useAppSelector } from '../../app/hooks'
import { usePermissions } from '../../shared/hooks/usePermissions'
import { useIsErpEnabled } from '../company/api'
import logoLight from '../../assets/logo-light.png'
import logoDark from '../../assets/logo-dark.png'
import { NAV_ITEMS } from './navConfig'

export function SideNav({ onNavigate }: { onNavigate?: () => void }) {
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
          alt="Blink Engage"
          sx={{ height: 28, width: 'auto' }}
        />
      </Toolbar>
      <List component="nav" aria-label="Main navigation" sx={{ px: 1 }}>
        {visibleItems.map((item) => {
          const selected = location.pathname === item.path
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
              <ListItemText primary={item.label} />
            </ListItemButton>
          )
        })}
      </List>
    </>
  )
}

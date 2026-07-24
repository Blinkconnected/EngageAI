import {
  List,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  Toolbar,
  Typography,
} from '@mui/material'
import { NavLink, useLocation } from 'react-router-dom'
import { usePermissions } from '../../shared/hooks/usePermissions'
import { NAV_ITEMS } from './navConfig'

export function SideNav({ onNavigate }: { onNavigate?: () => void }) {
  const { hasPermission } = usePermissions()
  const location = useLocation()

  const visibleItems = NAV_ITEMS.filter(
    (item) => !item.permission || hasPermission(item.permission),
  )

  return (
    <>
      <Toolbar>
        <Typography
          variant="h6"
          sx={{ fontWeight: 700, fontFamily: '"Baloo 2", system-ui, sans-serif' }}
        >
          Blink Engage
        </Typography>
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

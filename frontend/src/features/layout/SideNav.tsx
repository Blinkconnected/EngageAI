import { useCallback, useState } from 'react'
import {
  Box,
  Collapse,
  List,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  ListSubheader,
  Toolbar,
} from '@mui/material'
import ExpandLessIcon from '@mui/icons-material/ExpandLess'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import { NavLink, matchPath, useLocation } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useAppSelector } from '../../app/hooks'
import { usePermissions } from '../../shared/hooks/usePermissions'
import { useFeatures } from '../../shared/hooks/useFeatures'
import { useIsErpEnabled } from '../company/api'
import logoLight from '../../assets/logo-light.png'
import logoDark from '../../assets/logo-dark.png'
import { NAV_GROUPS, NAV_ITEMS, type NavGroupKey, type NavItem } from './navConfig'

/** Remembers which groups the reader left open, per browser.
 *
 * An administrator lives in Routing and Organisation; an agent never
 * opens either. Resetting on every navigation would make the sidebar
 * re-collapse under somebody mid-task. */
const EXPANDED_STORAGE_KEY = 'blinkengage.nav.expandedGroups'

function readStoredExpanded(): NavGroupKey[] {
  try {
    const raw = localStorage.getItem(EXPANDED_STORAGE_KEY)
    if (!raw) return []
    const parsed: unknown = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    const keys = NAV_GROUPS.map((group) => group.key) as string[]
    return parsed.filter((key): key is NavGroupKey => typeof key === 'string' && keys.includes(key))
  } catch {
    // A corrupted or unreadable value must not stop the sidebar
    // rendering — the worst case is starting collapsed.
    return []
  }
}

export function SideNav({ onNavigate }: { onNavigate?: () => void }) {
  const { t } = useTranslation('layout')
  const { hasPermission } = usePermissions()
  const location = useLocation()
  const isErpEnabled = useIsErpEnabled()
  const { hasFeature } = useFeatures()
  const themeMode = useAppSelector((state) => state.ui.themeMode)
  const [manuallyExpanded, setManuallyExpanded] = useState<NavGroupKey[]>(readStoredExpanded)

  const isVisible = useCallback(
    (item: NavItem) =>
      (!item.permission || hasPermission(item.permission)) &&
      (!item.requiresErpEnabled || isErpEnabled) &&
      (!item.requiresFeature || hasFeature(item.requiresFeature)),
    [hasPermission, isErpEnabled, hasFeature],
  )

  const isSelected = useCallback(
    (item: NavItem) => {
      // Prefix match (not exact equality) so a nested/detail route — a
      // conversation, a customer profile, a non-default Settings/Reports
      // tab — keeps its section highlighted instead of going blank.
      // `end: true` only for the root Dashboard item, or it would match
      // every path.
      const sectionPath = item.matchPath ?? item.path
      return matchPath({ path: sectionPath, end: sectionPath === '/' }, location.pathname) != null
    },
    [location.pathname],
  )

  const visibleItems = NAV_ITEMS.filter(isVisible)
  const topLevel = visibleItems.filter((item) => !item.group)

  function toggleGroup(key: NavGroupKey) {
    setManuallyExpanded((current) => {
      const next = current.includes(key)
        ? current.filter((entry) => entry !== key)
        : [...current, key]
      localStorage.setItem(EXPANDED_STORAGE_KEY, JSON.stringify(next))
      return next
    })
  }

  function renderItem(item: NavItem, nested: boolean) {
    const Icon = item.icon
    return (
      <ListItemButton
        key={item.path}
        component={NavLink}
        to={item.path}
        selected={isSelected(item)}
        onClick={onNavigate}
        sx={{ borderRadius: 2, mb: 0.5, ...(nested && { ps: 2 }) }}
      >
        <ListItemIcon sx={{ minWidth: 40 }}>
          <Icon fontSize="small" />
        </ListItemIcon>
        <ListItemText primary={t(item.label)} />
      </ListItemButton>
    )
  }

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
        {/* Dashboard first, then the groups, then Settings and Billing.
            Those three stay flat: each is a destination in its own right
            rather than one of several related screens, and burying the
            place people go to change things would be a step backwards. */}
        {topLevel.filter((item) => item.path === '/').map((item) => renderItem(item, false))}

        {NAV_GROUPS.map((group) => {
          const children = visibleItems.filter((item) => item.group === group.key)

          // A group nobody can see any of must not leave a heading
          // behind. Permissions and plan features already hide items, so
          // a restricted agent would otherwise be shown four empty
          // headings as an inventory of what they cannot access.
          if (children.length === 0) return null

          // One child does not need a disclosure triangle — that is
          // friction with nothing behind it. Render it flat instead.
          if (children.length === 1) return renderItem(children[0], false)

          const containsActive = children.some(isSelected)
          const open = containsActive || manuallyExpanded.includes(group.key)

          return (
            <Box key={group.key} sx={{ mb: 0.5 }}>
              <ListItemButton
                onClick={() => toggleGroup(group.key)}
                aria-expanded={open}
                sx={{ borderRadius: 2, py: 0.5 }}
              >
                <ListItemText
                  disableTypography
                  primary={
                    <ListSubheader
                      component="div"
                      disableGutters
                      sx={{
                        bgcolor: 'transparent',
                        lineHeight: 2,
                        fontSize: 11,
                        letterSpacing: '.08em',
                        textTransform: 'uppercase',
                      }}
                    >
                      {t(group.label)}
                    </ListSubheader>
                  }
                />
                {open ? <ExpandLessIcon fontSize="small" /> : <ExpandMoreIcon fontSize="small" />}
              </ListItemButton>
              <Collapse in={open} timeout="auto" unmountOnExit>
                <List component="div" disablePadding>
                  {children.map((item) => renderItem(item, true))}
                </List>
              </Collapse>
            </Box>
          )
        })}

        {topLevel.filter((item) => item.path !== '/').map((item) => renderItem(item, false))}
      </List>
    </>
  )
}

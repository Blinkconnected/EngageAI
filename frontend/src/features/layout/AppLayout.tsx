import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link as RouterLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import {
  Alert,
  AppBar,
  Avatar,
  Box,
  Divider,
  Drawer,
  IconButton,
  Link,
  ListItemIcon,
  ListItemText,
  MenuItem,
  MenuList,
  Popover,
  Toolbar,
  ToggleButton,
  ToggleButtonGroup,
  Tooltip,
  Typography,
  useMediaQuery,
  useTheme,
} from '@mui/material'
import DarkModeIcon from '@mui/icons-material/DarkMode'
import LightModeIcon from '@mui/icons-material/LightMode'
import TranslateIcon from '@mui/icons-material/Translate'
import LogoutIcon from '@mui/icons-material/Logout'
import MenuIcon from '@mui/icons-material/Menu'
import SearchIcon from '@mui/icons-material/Search'
import PersonOutlineIcon from '@mui/icons-material/PersonOutlineOutlined'
import { useAppDispatch, useAppSelector } from '../../app/hooks'
import { usePermissions } from '../../shared/hooks/usePermissions'
import i18n, { LANGUAGE_STORAGE_KEY, SUPPORTED_I18N_LANGUAGES } from '../../i18n'
import { useLanguageSync } from '../../i18n/useLanguageSync'
import { LANGUAGE_LABELS } from '../company/types'
import { setDirection, toggleThemeMode } from '../ui/uiSlice'
import { useAllAgentsQuery, useUpdateOwnAvailabilityMutation } from '../agents/api'
import type { SelfAvailabilityStatus } from '../agents/types'
import { useLogout } from '../auth/api'
import { useCurrentUserQuery } from '../session/api'
import { useCompanyLogoUrl, useCompanyQuery, useIsOnboardingIncomplete } from '../company/api'
import { NotificationBell } from '../notifications/NotificationBell'
import { GlobalSearchDialog } from '../search/GlobalSearchDialog'
import { NotificationToastProvider } from '../notifications/NotificationToastProvider'
import { RealtimeProvider } from '../realtime/RealtimeProvider'
import { Footer } from '../../shared/components/Footer'
import { OfflineBanner } from '../../shared/components/OfflineBanner'
import { SideNav } from './SideNav'

const DRAWER_WIDTH = 260

export function AppLayout() {
  const { t } = useTranslation('layout')
  const theme = useTheme()
  const isDesktop = useMediaQuery(theme.breakpoints.up('md'))
  const [mobileNavOpen, setMobileNavOpen] = useState(false)
  const [userMenuAnchor, setUserMenuAnchor] = useState<HTMLElement | null>(null)
  const [languageMenuAnchor, setLanguageMenuAnchor] = useState<HTMLElement | null>(null)
  const [searchOpen, setSearchOpen] = useState(false)

  // Cmd/Ctrl-K opens global search from anywhere in the app — the
  // near-universal shortcut for this, and the only way to reach search
  // without leaving the keyboard. Bound on window (not a specific
  // element) since it must work regardless of what's focused, but
  // deliberately ignored while the user is typing into a field, so it
  // can never swallow a genuine Ctrl-K in a text input.
  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key !== 'k' || !(event.metaKey || event.ctrlKey)) return
      const target = event.target as HTMLElement | null
      const tag = target?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || target?.isContentEditable) return
      event.preventDefault()
      setSearchOpen(true)
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [])

  const dispatch = useAppDispatch()
  const themeMode = useAppSelector((state) => state.ui.themeMode)
  const { data: currentUser } = useCurrentUserQuery()
  const { data: company } = useCompanyQuery()
  useLanguageSync(company?.settings.language)
  const { hasPermission } = usePermissions()
  const onboardingIncomplete = useIsOnboardingIncomplete()
  const logout = useLogout()
  const navigate = useNavigate()
  const location = useLocation()
  const showSetupBanner =
    onboardingIncomplete && hasPermission('company.manage') && location.pathname !== '/onboarding'

  // A personal, per-browser display preference — no permission needed
  // (unlike Settings -> Language, which changes the company-wide
  // default for everyone). Persisted so it survives a reload, and
  // recorded in localStorage precisely so useLanguageSync knows this
  // browser made an explicit choice and must stop re-applying the
  // company default over it.
  function handleSelectLanguage(nextLanguage: (typeof SUPPORTED_I18N_LANGUAGES)[number]) {
    setLanguageMenuAnchor(null)
    localStorage.setItem(LANGUAGE_STORAGE_KEY, nextLanguage)
    void i18n.changeLanguage(nextLanguage)
    dispatch(setDirection(nextLanguage === 'ar' ? 'rtl' : 'ltr'))
  }

  // Self-service availability (Online/Away/Busy) — deliberately not gated
  // by any permission (see useUpdateOwnAvailabilityMutation's docstring):
  // any authenticated agent may set their own status. Gated only by
  // actually *having* an Agent profile (a pure Owner who never became one
  // has nothing to set — PATCH /agents/me/status would 404).
  const myAgentsQuery = useAllAgentsQuery()
  const myAgent = myAgentsQuery.data?.find((agent) => agent.user_id === currentUser?.id)
  const updateAvailabilityMutation = useUpdateOwnAvailabilityMutation()

  const drawerContent = <SideNav onNavigate={() => setMobileNavOpen(false)} />
  const logoQuery = useCompanyLogoUrl(company?.settings.branding?.logo_key)

  return (
    <NotificationToastProvider>
      <RealtimeProvider>
        <Box sx={{ display: 'flex', minHeight: '100%' }}>
          <Box component="nav" sx={{ width: { md: DRAWER_WIDTH }, flexShrink: { md: 0 } }}>
            {isDesktop ? (
              <Drawer
                variant="permanent"
                open
                sx={{
                  '& .MuiDrawer-paper': {
                    width: DRAWER_WIDTH,
                    boxSizing: 'border-box',
                    borderRight: 1,
                    borderColor: 'divider',
                  },
                }}
              >
                {drawerContent}
              </Drawer>
            ) : (
              <Drawer
                variant="temporary"
                open={mobileNavOpen}
                onClose={() => setMobileNavOpen(false)}
                ModalProps={{ keepMounted: true }}
                sx={{ '& .MuiDrawer-paper': { width: DRAWER_WIDTH, boxSizing: 'border-box' } }}
              >
                {drawerContent}
              </Drawer>
            )}
          </Box>

          <Box
            sx={{
              display: 'flex',
              flexDirection: 'column',
              flexGrow: 1,
              minWidth: 0,
              minHeight: 0,
            }}
          >
            <OfflineBanner />
            <AppBar
              position="static"
              color="default"
              elevation={0}
              sx={{ borderBottom: 1, borderColor: 'divider' }}
            >
              <Toolbar>
                {!isDesktop && (
                  <IconButton
                    edge="start"
                    aria-label={t('AppLayout.openNavigationMenu')}
                    onClick={() => setMobileNavOpen(true)}
                    sx={{ mr: 1 }}
                  >
                    <MenuIcon />
                  </IconButton>
                )}
                {logoQuery.data && (
                  <Box
                    component="img"
                    src={logoQuery.data}
                    alt={t('AppLayout.companyLogoAlt', {
                      companyName: currentUser?.company.name ?? t('AppLayout.companyFallback'),
                    })}
                    sx={{ height: 28, width: 28, mr: 1, borderRadius: 0.5, objectFit: 'contain' }}
                  />
                )}
                <Typography
                  variant="h6"
                  component="div"
                  noWrap
                  sx={{ flexGrow: 1, minWidth: 0, fontWeight: 600 }}
                >
                  {currentUser?.company.name ?? t('AppLayout.appName')}
                </Typography>
                <Tooltip title={t('AppLayout.searchTooltip')}>
                  <IconButton
                    onClick={() => setSearchOpen(true)}
                    aria-label={t('AppLayout.searchAriaLabel')}
                  >
                    <SearchIcon />
                  </IconButton>
                </Tooltip>
                <NotificationBell />
                <Tooltip title={t('AppLayout.languageMenuTooltip')}>
                  <IconButton
                    onClick={(event) => setLanguageMenuAnchor(event.currentTarget)}
                    aria-label={t('AppLayout.languageMenuAriaLabel')}
                    aria-haspopup="true"
                  >
                    <TranslateIcon />
                  </IconButton>
                </Tooltip>
                {/* Popover + MenuList, not a bare Menu — same
                    aria-required-children reasoning as the account and
                    notification menus below: a role="menu" list only
                    accepts MenuItem children, and a raw <Divider>/label
                    row here isn't one. */}
                <Popover
                  open={Boolean(languageMenuAnchor)}
                  anchorEl={languageMenuAnchor}
                  onClose={() => setLanguageMenuAnchor(null)}
                  anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
                  transformOrigin={{ vertical: 'top', horizontal: 'right' }}
                >
                  <MenuList
                    sx={{ minWidth: 180 }}
                    aria-label={t('AppLayout.languageMenuAriaLabel')}
                  >
                    {SUPPORTED_I18N_LANGUAGES.map((code) => (
                      <MenuItem
                        key={code}
                        selected={i18n.language === code}
                        onClick={() => handleSelectLanguage(code)}
                      >
                        <ListItemText>{LANGUAGE_LABELS[code]}</ListItemText>
                      </MenuItem>
                    ))}
                  </MenuList>
                </Popover>
                <Tooltip title={t('AppLayout.toggleDarkModeTooltip')}>
                  <IconButton
                    onClick={() => dispatch(toggleThemeMode())}
                    aria-label={t('AppLayout.toggleThemeAriaLabel')}
                  >
                    {themeMode === 'dark' ? <LightModeIcon /> : <DarkModeIcon />}
                  </IconButton>
                </Tooltip>
                <Tooltip title={t('AppLayout.accountTooltip')}>
                  <IconButton
                    onClick={(event) => setUserMenuAnchor(event.currentTarget)}
                    aria-label={t('AppLayout.accountMenuAriaLabel')}
                    aria-haspopup="true"
                    sx={{ ml: 1 }}
                  >
                    <Avatar sx={{ width: 32, height: 32, fontSize: '0.9rem' }}>
                      {currentUser?.full_name?.charAt(0).toUpperCase() ?? '?'}
                    </Avatar>
                  </IconButton>
                </Tooltip>
                {/* Popover + MenuList, not a bare Menu: a MUI Menu renders
                    `role="menu"` on its list, which requires every direct
                    child to be a menuitem — the user-info block and the
                    availability ToggleButtonGroup below are neither, and
                    axe correctly flags that as aria-required-children.
                    Popover carries no such list role, so it can host
                    arbitrary content; MenuList (`autoFocusItem` moved
                    here) keeps the actual actions' keyboard behavior
                    (arrow-key navigation, Escape-to-close) identical to
                    before. */}
                <Popover
                  open={Boolean(userMenuAnchor)}
                  anchorEl={userMenuAnchor}
                  onClose={() => setUserMenuAnchor(null)}
                  anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
                  transformOrigin={{ vertical: 'top', horizontal: 'right' }}
                >
                  {currentUser && (
                    <Box sx={{ px: 2, py: 1, minWidth: 200 }}>
                      <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
                        {currentUser.full_name}
                      </Typography>
                      <Typography variant="body2" color="text.secondary">
                        {currentUser.email}
                      </Typography>
                      <Typography variant="caption" color="text.secondary">
                        {currentUser.roles.join(', ')}
                      </Typography>
                    </Box>
                  )}
                  {myAgent && (
                    <Box sx={{ px: 2, pb: 1 }}>
                      <Typography
                        id="availability-status-label"
                        variant="caption"
                        color="text.secondary"
                        component="div"
                        sx={{ mb: 0.5 }}
                      >
                        {t('AppLayout.statusLabel')}
                        {myAgent.status === 'offline' ? t('AppLayout.statusOfflineSuffix') : ''}
                      </Typography>
                      <ToggleButtonGroup
                        size="small"
                        fullWidth
                        exclusive
                        aria-labelledby="availability-status-label"
                        value={myAgent.status === 'offline' ? null : myAgent.status}
                        onChange={(_event, value: SelfAvailabilityStatus | null) => {
                          if (value) updateAvailabilityMutation.mutate(value)
                        }}
                      >
                        <ToggleButton value="online">{t('AppLayout.onlineStatus')}</ToggleButton>
                        <ToggleButton value="away">{t('AppLayout.awayStatus')}</ToggleButton>
                        <ToggleButton value="busy">{t('AppLayout.busyStatus')}</ToggleButton>
                      </ToggleButtonGroup>
                    </Box>
                  )}
                  <Divider />
                  <MenuList autoFocusItem={Boolean(userMenuAnchor)}>
                    <MenuItem
                      onClick={() => {
                        setUserMenuAnchor(null)
                        navigate('/profile')
                      }}
                    >
                      <ListItemIcon>
                        <PersonOutlineIcon fontSize="small" />
                      </ListItemIcon>
                      <ListItemText>{t('AppLayout.myProfile')}</ListItemText>
                    </MenuItem>
                    <MenuItem
                      onClick={() => {
                        setUserMenuAnchor(null)
                        void logout()
                      }}
                    >
                      <ListItemIcon>
                        <LogoutIcon fontSize="small" />
                      </ListItemIcon>
                      <ListItemText>{t('AppLayout.signOut')}</ListItemText>
                    </MenuItem>
                  </MenuList>
                </Popover>
              </Toolbar>
            </AppBar>
            {/* `minHeight: 0` overrides flexbox's automatic minimum size (a
                flex item otherwise refuses to shrink below its content's
                natural height, which would silently defeat every page's
                ability to scroll internally instead of growing the whole
                document) — combined with `overflowY: 'auto'`, this makes
                `main` the one scroll container for ordinary pages (nav/
                header/footer now stay put instead of scrolling away with
                them), and gives any page that wants full internal control
                over its own scrolling (e.g. the conversation workspace,
                where only the message thread should scroll) a properly
                height-bounded ancestor to size against. */}
            <Box component="main" sx={{ flexGrow: 1, minHeight: 0, overflowY: 'auto', p: 3 }}>
              {showSetupBanner && (
                <Alert severity="info" sx={{ mb: 2 }}>
                  {t('AppLayout.setupBannerMessage')}{' '}
                  <Link component={RouterLink} to="/onboarding">
                    {t('AppLayout.setupBannerLink')}
                  </Link>
                </Alert>
              )}
              <Outlet />
            </Box>
            <Footer />
          </Box>
        </Box>
        <GlobalSearchDialog open={searchOpen} onClose={() => setSearchOpen(false)} />
      </RealtimeProvider>
    </NotificationToastProvider>
  )
}

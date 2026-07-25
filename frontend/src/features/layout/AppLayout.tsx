import { useState } from 'react'
import { Outlet, useNavigate } from 'react-router-dom'
import {
  AppBar,
  Avatar,
  Box,
  Divider,
  Drawer,
  IconButton,
  ListItemIcon,
  ListItemText,
  Menu,
  MenuItem,
  Toolbar,
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
import PersonOutlineIcon from '@mui/icons-material/PersonOutlineOutlined'
import { useAppDispatch, useAppSelector } from '../../app/hooks'
import { setDirection, toggleThemeMode } from '../ui/uiSlice'
import { useLogout } from '../auth/api'
import { useCurrentUserQuery } from '../session/api'
import { NotificationBell } from '../notifications/NotificationBell'
import { RealtimeProvider } from '../realtime/RealtimeProvider'
import { SideNav } from './SideNav'

const DRAWER_WIDTH = 260

export function AppLayout() {
  const theme = useTheme()
  const isDesktop = useMediaQuery(theme.breakpoints.up('md'))
  const [mobileNavOpen, setMobileNavOpen] = useState(false)
  const [userMenuAnchor, setUserMenuAnchor] = useState<HTMLElement | null>(null)

  const dispatch = useAppDispatch()
  const themeMode = useAppSelector((state) => state.ui.themeMode)
  const direction = useAppSelector((state) => state.ui.direction)
  const { data: currentUser } = useCurrentUserQuery()
  const logout = useLogout()
  const navigate = useNavigate()

  const drawerContent = <SideNav onNavigate={() => setMobileNavOpen(false)} />

  return (
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

        <Box sx={{ display: 'flex', flexDirection: 'column', flexGrow: 1, minWidth: 0 }}>
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
                  aria-label="Open navigation menu"
                  onClick={() => setMobileNavOpen(true)}
                  sx={{ mr: 1 }}
                >
                  <MenuIcon />
                </IconButton>
              )}
              <Typography variant="h6" component="div" sx={{ flexGrow: 1, fontWeight: 600 }}>
                {currentUser?.company.name ?? 'Blink Engage'}
              </Typography>
              <NotificationBell />
              <Tooltip title="Toggle language direction">
                <IconButton
                  onClick={() => dispatch(setDirection(direction === 'ltr' ? 'rtl' : 'ltr'))}
                  aria-label="toggle direction"
                >
                  <TranslateIcon />
                </IconButton>
              </Tooltip>
              <Tooltip title="Toggle dark mode">
                <IconButton onClick={() => dispatch(toggleThemeMode())} aria-label="toggle theme">
                  {themeMode === 'dark' ? <LightModeIcon /> : <DarkModeIcon />}
                </IconButton>
              </Tooltip>
              <Tooltip title="Account">
                <IconButton
                  onClick={(event) => setUserMenuAnchor(event.currentTarget)}
                  aria-label="account menu"
                  aria-haspopup="true"
                  sx={{ ml: 1 }}
                >
                  <Avatar sx={{ width: 32, height: 32, fontSize: '0.9rem' }}>
                    {currentUser?.full_name?.charAt(0).toUpperCase() ?? '?'}
                  </Avatar>
                </IconButton>
              </Tooltip>
              <Menu
                anchorEl={userMenuAnchor}
                open={Boolean(userMenuAnchor)}
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
                <Divider />
                <MenuItem
                  onClick={() => {
                    setUserMenuAnchor(null)
                    navigate('/profile')
                  }}
                >
                  <ListItemIcon>
                    <PersonOutlineIcon fontSize="small" />
                  </ListItemIcon>
                  <ListItemText>My Profile</ListItemText>
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
                  <ListItemText>Sign out</ListItemText>
                </MenuItem>
              </Menu>
            </Toolbar>
          </AppBar>
          <Box component="main" sx={{ flexGrow: 1, p: 3 }}>
            <Outlet />
          </Box>
        </Box>
      </Box>
    </RealtimeProvider>
  )
}

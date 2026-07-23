import { Outlet } from 'react-router-dom'
import { AppBar, Box, IconButton, Toolbar, Tooltip, Typography } from '@mui/material'
import DarkModeIcon from '@mui/icons-material/DarkMode'
import LightModeIcon from '@mui/icons-material/LightMode'
import TranslateIcon from '@mui/icons-material/Translate'
import LogoutIcon from '@mui/icons-material/Logout'
import { useAppDispatch, useAppSelector } from '../../app/hooks'
import { setDirection, toggleThemeMode } from '../ui/uiSlice'
import { useLogout } from '../auth/api'

export function AppLayout() {
  const dispatch = useAppDispatch()
  const themeMode = useAppSelector((state) => state.ui.themeMode)
  const direction = useAppSelector((state) => state.ui.direction)
  const user = useAppSelector((state) => state.auth.user)
  const logout = useLogout()

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', minHeight: '100%' }}>
      <AppBar
        position="static"
        color="default"
        elevation={0}
        sx={{ borderBottom: 1, borderColor: 'divider' }}
      >
        <Toolbar>
          <Typography variant="h6" component="div" sx={{ flexGrow: 1, fontWeight: 600 }}>
            Blink Engage
          </Typography>
          {user && (
            <Typography variant="body2" color="text.secondary" sx={{ mr: 2 }}>
              {user.fullName}
            </Typography>
          )}
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
          <Tooltip title="Sign out">
            <IconButton onClick={() => void logout()} aria-label="sign out">
              <LogoutIcon />
            </IconButton>
          </Tooltip>
        </Toolbar>
      </AppBar>
      <Box component="main" sx={{ flexGrow: 1, p: 3 }}>
        <Outlet />
      </Box>
    </Box>
  )
}

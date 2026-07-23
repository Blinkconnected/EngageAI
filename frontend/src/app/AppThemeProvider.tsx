import { useEffect, useMemo, type ReactNode } from 'react'
import { CacheProvider } from '@emotion/react'
import { CssBaseline, ThemeProvider } from '@mui/material'
import { useAppSelector } from './hooks'
import { createAppTheme } from '../theme/theme'
import { createEmotionCache } from '../theme/emotionCache'

export function AppThemeProvider({ children }: { children: ReactNode }) {
  const themeMode = useAppSelector((state) => state.ui.themeMode)
  const direction = useAppSelector((state) => state.ui.direction)

  const theme = useMemo(() => createAppTheme(themeMode, direction), [themeMode, direction])
  const emotionCache = useMemo(() => createEmotionCache(direction), [direction])

  useEffect(() => {
    document.documentElement.setAttribute('dir', direction)
    document.documentElement.setAttribute('lang', direction === 'rtl' ? 'ar' : 'en')
  }, [direction])

  return (
    <CacheProvider value={emotionCache}>
      <ThemeProvider theme={theme}>
        <CssBaseline />
        {children}
      </ThemeProvider>
    </CacheProvider>
  )
}

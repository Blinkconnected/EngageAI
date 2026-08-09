import { Button, IconButton, Stack, Tooltip } from '@mui/material'
import DarkModeOutlinedIcon from '@mui/icons-material/DarkModeOutlined'
import LightModeOutlinedIcon from '@mui/icons-material/LightModeOutlined'
import { useTranslation } from 'react-i18next'
import { useAppDispatch, useAppSelector } from '../../app/hooks'
import i18n, { LANGUAGE_STORAGE_KEY } from '../../i18n'
import { setDirection, toggleThemeMode } from '../../features/ui/uiSlice'

/**
 * Language and theme switches for screens outside the signed-in shell.
 *
 * `AppLayout` has its own copies of these, wired into a larger toolbar
 * alongside notifications, search and availability. They are not shared
 * here because extracting them would mean reshaping a working 300-line
 * component for the benefit of one new page — a change with more risk
 * than the duplication it removes. Consolidating the two is worth doing
 * when the next surface needs them; at that point there are three
 * callers and the refactor pays for itself.
 *
 * Deliberately not a language *menu*: with exactly two languages, a
 * toggle is one interaction instead of two, and the label always shows
 * the language you would switch *to* rather than the one you are in —
 * which is the ambiguity that makes two-item language menus annoying.
 */
export function LanguageThemeControls() {
  const { t } = useTranslation('shared')
  const dispatch = useAppDispatch()
  const themeMode = useAppSelector((state) => state.ui.themeMode)
  const isArabic = i18n.language.startsWith('ar')

  function switchLanguage() {
    const next = isArabic ? 'en' : 'ar'
    localStorage.setItem(LANGUAGE_STORAGE_KEY, next)
    void i18n.changeLanguage(next)
    dispatch(setDirection(next === 'ar' ? 'rtl' : 'ltr'))
  }

  return (
    <Stack direction="row" spacing={0.5} sx={{ alignItems: 'center' }}>
      <Button
        onClick={switchLanguage}
        size="small"
        color="inherit"
        aria-label={t('LanguageThemeControls.switchLanguage')}
      >
        {isArabic ? 'English' : 'العربية'}
      </Button>
      <Tooltip title={t('LanguageThemeControls.toggleTheme')}>
        <IconButton
          onClick={() => dispatch(toggleThemeMode())}
          size="small"
          color="inherit"
          aria-label={t('LanguageThemeControls.toggleTheme')}
        >
          {themeMode === 'dark' ? (
            <LightModeOutlinedIcon fontSize="small" />
          ) : (
            <DarkModeOutlinedIcon fontSize="small" />
          )}
        </IconButton>
      </Tooltip>
    </Stack>
  )
}

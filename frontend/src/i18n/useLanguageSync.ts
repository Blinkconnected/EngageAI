import { useEffect } from 'react'
import i18n, { LANGUAGE_STORAGE_KEY, SUPPORTED_I18N_LANGUAGES, type SupportedI18nLanguage } from '.'
import { useAppDispatch } from '../app/hooks'
import { setDirection } from '../features/ui/uiSlice'
import type { SupportedLanguage } from '../features/company/types'

function toI18nLanguage(language: SupportedLanguage): SupportedI18nLanguage {
  return (SUPPORTED_I18N_LANGUAGES as readonly string[]).includes(language)
    ? (language as SupportedI18nLanguage)
    : 'en'
}

/** Applies a resolved language (the company's `settings.language`,
 * defaulting to English before that's loaded or for a language without
 * its own catalog yet, e.g. French/Spanish — see `SUPPORTED_I18N_LANGUAGES`)
 * as the actual rendered UI language, and defaults text direction to
 * match it.
 *
 * Skipped entirely once this browser has made an explicit choice via the
 * AppBar's language menu (`LANGUAGE_STORAGE_KEY` set — see
 * `AppLayout.tsx`'s `LanguageMenu`): that choice is a personal display
 * preference for this browser, and must not be silently overwritten back
 * to the company-wide default every time this effect's dependency
 * (`language`) changes — e.g. on a fresh page load once `company` finishes
 * loading. Direction stays independent Redux state either way — this
 * only sets its *default* whenever the resolved language changes, same
 * as before. */
export function useLanguageSync(language: SupportedLanguage | undefined) {
  const dispatch = useAppDispatch()

  useEffect(() => {
    if (localStorage.getItem(LANGUAGE_STORAGE_KEY)) return
    const resolved = toI18nLanguage(language ?? 'en')
    if (i18n.language !== resolved) {
      void i18n.changeLanguage(resolved)
      dispatch(setDirection(resolved === 'ar' ? 'rtl' : 'ltr'))
    }
  }, [language, dispatch])
}

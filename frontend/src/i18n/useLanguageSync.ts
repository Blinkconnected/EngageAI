import { useEffect } from 'react'
import i18n, { SUPPORTED_I18N_LANGUAGES, type SupportedI18nLanguage } from '.'
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
 * match it. Direction stays independent Redux state afterward — the
 * topbar's manual "Toggle language direction" button still works as a
 * same-session override — this only sets the *default* whenever the
 * resolved language changes. */
export function useLanguageSync(language: SupportedLanguage | undefined) {
  const dispatch = useAppDispatch()

  useEffect(() => {
    const resolved = toI18nLanguage(language ?? 'en')
    if (i18n.language !== resolved) {
      void i18n.changeLanguage(resolved)
      dispatch(setDirection(resolved === 'ar' ? 'rtl' : 'ltr'))
    }
  }, [language, dispatch])
}

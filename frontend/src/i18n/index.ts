import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'

import enAgents from '../locales/en/agents.json'
import enAuth from '../locales/en/auth.json'
import enChangelog from '../locales/en/changelog.json'
import enChannelsCore from '../locales/en/channelsCore.json'
import enChannelsFields from '../locales/en/channelsFields.json'
import enCompanySettings from '../locales/en/companySettings.json'
import enCompanySettingsExtra from '../locales/en/companySettingsExtra.json'
import enConversationsCore from '../locales/en/conversationsCore.json'
import enConversationsExtra from '../locales/en/conversationsExtra.json'
import enCustomers from '../locales/en/customers.json'
import enDashboard from '../locales/en/dashboard.json'
import enDepartments from '../locales/en/departments.json'
import enErp from '../locales/en/erp.json'
import enFeedback from '../locales/en/feedback.json'
import enLayout from '../locales/en/layout.json'
import enNotifications from '../locales/en/notifications.json'
import enOnboarding from '../locales/en/onboarding.json'
import enProfile from '../locales/en/profile.json'
import enQueues from '../locales/en/queues.json'
import enReportsCore from '../locales/en/reportsCore.json'
import enReportsPanels from '../locales/en/reportsPanels.json'
import enRoles from '../locales/en/roles.json'
import enSearch from '../locales/en/search.json'
import enSla from '../locales/en/sla.json'
import enStatus from '../locales/en/status.json'
import enPlatform from '../locales/en/platform.json'
import enBilling from '../locales/en/billing.json'
import enPages from '../locales/en/pages.json'
import enShared from '../locales/en/shared.json'

import arAgents from '../locales/ar/agents.json'
import arAuth from '../locales/ar/auth.json'
import arChangelog from '../locales/ar/changelog.json'
import arChannelsCore from '../locales/ar/channelsCore.json'
import arChannelsFields from '../locales/ar/channelsFields.json'
import arCompanySettings from '../locales/ar/companySettings.json'
import arCompanySettingsExtra from '../locales/ar/companySettingsExtra.json'
import arConversationsCore from '../locales/ar/conversationsCore.json'
import arConversationsExtra from '../locales/ar/conversationsExtra.json'
import arCustomers from '../locales/ar/customers.json'
import arDashboard from '../locales/ar/dashboard.json'
import arDepartments from '../locales/ar/departments.json'
import arErp from '../locales/ar/erp.json'
import arFeedback from '../locales/ar/feedback.json'
import arLayout from '../locales/ar/layout.json'
import arNotifications from '../locales/ar/notifications.json'
import arOnboarding from '../locales/ar/onboarding.json'
import arProfile from '../locales/ar/profile.json'
import arQueues from '../locales/ar/queues.json'
import arReportsCore from '../locales/ar/reportsCore.json'
import arReportsPanels from '../locales/ar/reportsPanels.json'
import arRoles from '../locales/ar/roles.json'
import arSearch from '../locales/ar/search.json'
import arSla from '../locales/ar/sla.json'
import arStatus from '../locales/ar/status.json'
import arPlatform from '../locales/ar/platform.json'
import arBilling from '../locales/ar/billing.json'
import arPages from '../locales/ar/pages.json'
import arShared from '../locales/ar/shared.json'

// One namespace per feature directory (a couple of larger directories —
// channels, company, conversations, reports — are split into two so no
// single namespace file/PR-sized chunk of work gets unwieldy). Every
// namespace is bundled and registered up front (no lazy backend/HTTP
// loading) so `i18next.init` below completes synchronously: components
// can call `t(...)` on their very first render, in both the real app and
// in vitest (jsdom) — no loading-flash, no async race to guard against.
export const NAMESPACES = [
  'agents',
  'auth',
  'changelog',
  'channelsCore',
  'channelsFields',
  'companySettings',
  'companySettingsExtra',
  'conversationsCore',
  'conversationsExtra',
  'customers',
  'dashboard',
  'departments',
  'erp',
  'feedback',
  'layout',
  'notifications',
  'onboarding',
  'profile',
  'queues',
  'reportsCore',
  'reportsPanels',
  'roles',
  'search',
  'sla',
  'status',
  'pages',
  'platform',
  'billing',
  'shared',
] as const

export type Namespace = (typeof NAMESPACES)[number]

// Only languages with a real, human-reviewed translation catalog belong
// here. `company/types.ts`'s `SUPPORTED_LANGUAGES` still lists a couple of
// languages beyond these (kept for backward compatibility with any
// already-stored company setting) that intentionally aren't offered in
// the Settings dropdown until they have their own catalog — see
// `LanguageSettingsPanel.tsx`.
export const SUPPORTED_I18N_LANGUAGES = ['en', 'ar'] as const
export type SupportedI18nLanguage = (typeof SUPPORTED_I18N_LANGUAGES)[number]

// A manual, per-browser language choice from the AppBar's language menu
// (see AppLayout.tsx) — read once here as the *initial* language so it
// survives a page reload, the same way uiSlice.ts's themeMode/direction
// already persist. Distinct from useLanguageSync's company-wide
// `settings.language` default: this key existing means "this browser
// explicitly chose a language," which useLanguageSync must not silently
// overwrite back to the company default on every mount.
export const LANGUAGE_STORAGE_KEY = 'blinkengage.language'

function readStoredLanguage(): SupportedI18nLanguage | null {
  const stored = localStorage.getItem(LANGUAGE_STORAGE_KEY)
  return (SUPPORTED_I18N_LANGUAGES as readonly string[]).includes(stored ?? '')
    ? (stored as SupportedI18nLanguage)
    : null
}

void i18n.use(initReactI18next).init({
  resources: {
    en: {
      agents: enAgents,
      auth: enAuth,
      changelog: enChangelog,
      channelsCore: enChannelsCore,
      channelsFields: enChannelsFields,
      companySettings: enCompanySettings,
      companySettingsExtra: enCompanySettingsExtra,
      conversationsCore: enConversationsCore,
      conversationsExtra: enConversationsExtra,
      customers: enCustomers,
      dashboard: enDashboard,
      departments: enDepartments,
      erp: enErp,
      feedback: enFeedback,
      layout: enLayout,
      notifications: enNotifications,
      onboarding: enOnboarding,
      profile: enProfile,
      queues: enQueues,
      reportsCore: enReportsCore,
      reportsPanels: enReportsPanels,
      roles: enRoles,
      search: enSearch,
      sla: enSla,
      status: enStatus,
      pages: enPages,
      platform: enPlatform,
      billing: enBilling,
      shared: enShared,
    },
    ar: {
      agents: arAgents,
      auth: arAuth,
      changelog: arChangelog,
      channelsCore: arChannelsCore,
      channelsFields: arChannelsFields,
      companySettings: arCompanySettings,
      companySettingsExtra: arCompanySettingsExtra,
      conversationsCore: arConversationsCore,
      conversationsExtra: arConversationsExtra,
      customers: arCustomers,
      dashboard: arDashboard,
      departments: arDepartments,
      erp: arErp,
      feedback: arFeedback,
      layout: arLayout,
      notifications: arNotifications,
      onboarding: arOnboarding,
      profile: arProfile,
      queues: arQueues,
      reportsCore: arReportsCore,
      reportsPanels: arReportsPanels,
      roles: arRoles,
      search: arSearch,
      sla: arSla,
      status: arStatus,
      pages: arPages,
      platform: arPlatform,
      billing: arBilling,
      shared: arShared,
    },
  },
  ns: NAMESPACES,
  lng: readStoredLanguage() ?? 'en',
  fallbackLng: 'en',
  // React already escapes interpolated values.
  interpolation: { escapeValue: false },
  // No backend/loadPath is configured — every resource above is bundled
  // directly, so `init()` resolves synchronously with no network/fs
  // round trip; `t()` is correct from a component's very first render.
})

export default i18n

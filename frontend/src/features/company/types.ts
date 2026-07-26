export type CompanyStatus = 'trial' | 'active' | 'suspended'

export const SUPPORTED_LANGUAGES = ['en', 'ar', 'fr', 'es'] as const
export type SupportedLanguage = (typeof SUPPORTED_LANGUAGES)[number]

export const LANGUAGE_LABELS: Record<SupportedLanguage, string> = {
  en: 'English',
  ar: 'Arabic',
  fr: 'French',
  es: 'Spanish',
}

export const WEEKDAYS = [
  'monday',
  'tuesday',
  'wednesday',
  'thursday',
  'friday',
  'saturday',
  'sunday',
] as const
export type Weekday = (typeof WEEKDAYS)[number]

export interface BusinessHoursDay {
  open: string
  close: string
  closed: boolean
}

export interface BrandingSettings {
  logo_url?: string | null
}

export interface BusinessHoursSettings {
  enabled: boolean
  schedule?: Partial<Record<Weekday, BusinessHoursDay>>
}

export interface MessagingSettings {
  typing_indicator_enabled: boolean
}

export interface SecuritySettings {
  min_password_length: number
}

export interface AiSettings {
  enabled: boolean
}

export interface ErpSettings {
  enabled: boolean
}

export interface OnboardingSettings {
  completed: boolean
}

/** Every field is a full replacement of that top-level section — a
 * settings tab always sends its own section's complete current state,
 * matching the backend's shallow-merge-per-top-level-key semantics. */
export interface CompanySettings {
  onboarding?: OnboardingSettings
  branding?: BrandingSettings
  language?: SupportedLanguage
  timezone?: string
  business_hours?: BusinessHoursSettings
  notifications?: Record<string, boolean>
  messaging?: MessagingSettings
  security?: SecuritySettings
  ai?: AiSettings
  erp?: ErpSettings
}

/** Matches the backend's `CompanyResponse` (`GET`/`PATCH /company`). */
export interface Company {
  id: string
  name: string
  slug: string
  status: CompanyStatus
  settings: CompanySettings
  created_at: string
  updated_at: string
}

export interface CompanyUpdateRequest {
  name?: string
  settings?: CompanySettings
}

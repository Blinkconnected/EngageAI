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

/** Read-only from the client's perspective — set exclusively via
 * `POST`/`DELETE /company/logo` (see `api.ts`'s `useUploadCompanyLogoMutation`/
 * `useDeleteCompanyLogoMutation`), never through the generic company
 * settings PATCH. `logo_key` is an internal storage reference, not a
 * fetchable URL — the actual bytes come from `GET /company/logo`
 * (`useCompanyLogoUrl`), same authenticated-blob-fetch pattern as
 * message attachments. */
export interface BrandingSettings {
  logo_key?: string | null
  logo_content_type?: string | null
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

export interface AutopilotSettings {
  /** Master switch. With this off, no activation mode does anything. */
  enabled: boolean
  confidence_threshold: number
  /** Engage on a brand-new conversation routed to an Autopilot-enabled
   * queue. Defaults true server-side — the only mode that existed before
   * modes did, so a company that never touched these keeps behaving
   * exactly as before. */
  activate_on_new_conversation?: boolean
  /** Engage when a conversation crosses its SLA warning threshold or
   * breaches, so an unanswered customer still gets a reply. */
  activate_on_sla?: boolean
  /** Engage only when an agent explicitly hands the conversation over. */
  activate_on_agent_request?: boolean
}

export interface AiSettings {
  // Optional, not just at the top-level `ai` key (which every other
  // section already treats this way) — this section itself is only
  // ever sent as a one-level-deep partial patch (see
  // CompanyService._merge_settings), so a PATCH updating just
  // `autopilot` doesn't need to restate `enabled`.
  enabled?: boolean
  autopilot?: AutopilotSettings
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

export type AiConfigProvider =
  'openai' | 'claude' | 'gemini' | 'azure_openai' | 'ollama' | 'mistral' | 'groq' | 'deepseek'

export const AI_CONFIG_PROVIDERS: { value: AiConfigProvider; label: string }[] = [
  { value: 'openai', label: 'OpenAI' },
  { value: 'claude', label: 'Claude (Anthropic)' },
  { value: 'gemini', label: 'Gemini (Google)' },
  { value: 'azure_openai', label: 'Azure OpenAI' },
  { value: 'mistral', label: 'Mistral' },
  { value: 'groq', label: 'Groq' },
  { value: 'deepseek', label: 'DeepSeek' },
  { value: 'ollama', label: 'Ollama (self-hosted)' },
]

/** Matches the backend's `AiConfigResponse` (`GET /company/ai-config`) —
 * never carries the raw API key, only whether one is saved.
 * `deployment_name`/`api_version` are only meaningful for `azure_openai`
 * — every other provider leaves them `null`. */
export interface AiConfig {
  provider: AiConfigProvider | null
  model: string | null
  base_url: string | null
  api_key_set: boolean
  deployment_name: string | null
  api_version: string | null
}

/** `provider: null` clears the override entirely (reverts to the
 * platform default). `api_key` omitted/undefined leaves any previously
 * saved key untouched — see the backend schema's own docstring. */
export interface AiConfigUpdateRequest {
  provider: AiConfigProvider | null
  api_key?: string
  model?: string | null
  base_url?: string | null
  deployment_name?: string | null
  api_version?: string | null
}

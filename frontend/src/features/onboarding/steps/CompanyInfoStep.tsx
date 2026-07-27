import { Stack } from '@mui/material'
import { BrandingSettingsPanel } from '../../company/panels/BrandingSettingsPanel'
import { BusinessHoursSettingsPanel } from '../../company/panels/BusinessHoursSettingsPanel'
import { GeneralSettingsPanel } from '../../company/panels/GeneralSettingsPanel'
import { LanguageSettingsPanel } from '../../company/panels/LanguageSettingsPanel'
import { TimezoneSettingsPanel } from '../../company/panels/TimezoneSettingsPanel'
import type { Company } from '../../company/types'

/** Reuses the exact same panels Settings uses. Each one persists
 * independently of the others (Branding on file upload, everything else
 * via its own "Save changes" button) — "Next" doesn't trigger or require
 * a save itself, so anything left un-saved here simply keeps its prior
 * value (or schema default) and can be finished later from Settings. See
 * docs/architecture/company-onboarding.md. */
export function CompanyInfoStep({ company }: { company: Company }) {
  return (
    <Stack spacing={3}>
      <GeneralSettingsPanel company={company} />
      <BrandingSettingsPanel company={company} />
      <TimezoneSettingsPanel company={company} />
      <LanguageSettingsPanel company={company} />
      <BusinessHoursSettingsPanel company={company} />
    </Stack>
  )
}

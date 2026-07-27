import { useState } from 'react'
import {
  Alert,
  Card,
  CardContent,
  FormControlLabel,
  Stack,
  Switch,
  Typography,
} from '@mui/material'
import { useTranslation } from 'react-i18next'
import { extractErrorMessage } from '../../../shared/api/errors'
import { useUpdateCompanyMutation } from '../api'
import type { Company } from '../types'

/** The always-visible master switch for ERP integration — deliberately
 * lives on the General tab, not the (conditionally-hidden) ERP tab
 * itself, since something has to be reachable to turn it back on. Once
 * enabled, a dedicated "ERP" tab appears with the actual connection
 * form. See docs/architecture/company-onboarding.md. */
export function ErpEnableToggle({ company }: { company: Company }) {
  const { t } = useTranslation('companySettings')
  const [enabled, setEnabled] = useState(company.settings.erp?.enabled ?? false)
  const updateMutation = useUpdateCompanyMutation()

  function handleChange(next: boolean) {
    setEnabled(next)
    updateMutation.mutate(
      { settings: { erp: { enabled: next } } },
      { onError: () => setEnabled(!next) },
    )
  }

  return (
    <Card variant="outlined" sx={{ maxWidth: 520 }}>
      <CardContent>
        <Stack spacing={2}>
          {updateMutation.isError && (
            <Alert severity="error">{extractErrorMessage(updateMutation.error)}</Alert>
          )}

          <FormControlLabel
            control={
              <Switch checked={enabled} onChange={(event) => handleChange(event.target.checked)} />
            }
            label={t('ErpEnableToggle.enableLabel')}
          />
          <Typography variant="body2" color="text.secondary">
            {t('ErpEnableToggle.description')}
          </Typography>
        </Stack>
      </CardContent>
    </Card>
  )
}

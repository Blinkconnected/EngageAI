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
import { extractErrorMessage } from '../../../shared/api/errors'
import { useUpdateCompanyMutation } from '../api'
import type { Company } from '../types'

/** The always-visible master switch for ERP integration — deliberately
 * lives on the General tab, not the (conditionally-hidden) ERP tab
 * itself, since something has to be reachable to turn it back on. Once
 * enabled, a dedicated "ERP" tab appears with the actual connection
 * form. See docs/architecture/company-onboarding.md. */
export function ErpEnableToggle({ company }: { company: Company }) {
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
            label="Enable ERP Integration"
          />
          <Typography variant="body2" color="text.secondary">
            Connect ERPNext to sync customer records. Once enabled, a new "ERP" tab appears here
            to configure the connection. Turning this off completely hides ERP everywhere —
            navigation, customer profiles, and reports — without losing a saved connection.
          </Typography>
        </Stack>
      </CardContent>
    </Card>
  )
}

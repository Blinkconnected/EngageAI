import { useMemo, useState } from 'react'
import {
  Alert,
  Autocomplete,
  Button,
  Card,
  CardContent,
  Stack,
  TextField,
  Typography,
} from '@mui/material'
import { useTranslation } from 'react-i18next'
import { extractErrorMessage } from '../../../shared/api/errors'
import { useUpdateCompanyMutation } from '../api'
import type { Company } from '../types'

function supportedTimezones(): string[] {
  try {
    return Intl.supportedValuesOf('timeZone')
  } catch {
    return ['UTC']
  }
}

export function TimezoneSettingsPanel({ company }: { company: Company }) {
  const { t } = useTranslation('companySettings')
  const options = useMemo(() => supportedTimezones(), [])
  const [timezone, setTimezone] = useState(company.settings.timezone ?? 'UTC')
  const updateMutation = useUpdateCompanyMutation()
  const savedTimezone = company.settings.timezone ?? 'UTC'
  const isDirty = timezone !== savedTimezone

  return (
    <Card variant="outlined" sx={{ maxWidth: 520 }}>
      <CardContent>
        <Stack spacing={2}>
          <Typography variant="body2" color="text.secondary">
            {t('TimezoneSettingsPanel.description')}
          </Typography>

          {updateMutation.isError && (
            <Alert severity="error">{extractErrorMessage(updateMutation.error)}</Alert>
          )}
          {updateMutation.isSuccess && !isDirty && (
            <Alert severity="success">{t('TimezoneSettingsPanel.savedMessage')}</Alert>
          )}

          <Autocomplete
            options={options}
            value={timezone}
            onChange={(_event, value) => setTimezone(value ?? 'UTC')}
            disableClearable
            renderInput={(params) => (
              <TextField {...params} label={t('TimezoneSettingsPanel.timezoneLabel')} />
            )}
          />

          <Button
            variant="contained"
            disabled={updateMutation.isPending || !isDirty}
            onClick={() => updateMutation.mutate({ settings: { timezone } })}
            sx={{ alignSelf: 'flex-start' }}
          >
            {updateMutation.isPending
              ? t('TimezoneSettingsPanel.savingButton')
              : t('TimezoneSettingsPanel.saveChangesButton')}
          </Button>
        </Stack>
      </CardContent>
    </Card>
  )
}

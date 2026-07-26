import { useMemo, useState } from 'react'
import { Alert, Autocomplete, Button, Card, CardContent, Stack, TextField, Typography } from '@mui/material'
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
  const options = useMemo(() => supportedTimezones(), [])
  const [timezone, setTimezone] = useState(company.settings.timezone ?? 'UTC')
  const updateMutation = useUpdateCompanyMutation()
  const savedTimezone = company.settings.timezone ?? 'UTC'

  return (
    <Card variant="outlined" sx={{ maxWidth: 520 }}>
      <CardContent>
        <Stack spacing={2}>
          <Typography variant="body2" color="text.secondary">
            Used to display times consistently across reports and business hours.
          </Typography>

          {updateMutation.isError && (
            <Alert severity="error">{extractErrorMessage(updateMutation.error)}</Alert>
          )}
          {updateMutation.isSuccess && <Alert severity="success">Saved.</Alert>}

          <Autocomplete
            options={options}
            value={timezone}
            onChange={(_event, value) => setTimezone(value ?? 'UTC')}
            disableClearable
            renderInput={(params) => <TextField {...params} label="Timezone" />}
          />

          <Button
            variant="contained"
            disabled={updateMutation.isPending || timezone === savedTimezone}
            onClick={() => updateMutation.mutate({ settings: { timezone } })}
            sx={{ alignSelf: 'flex-start' }}
          >
            {updateMutation.isPending ? 'Saving…' : 'Save changes'}
          </Button>
        </Stack>
      </CardContent>
    </Card>
  )
}

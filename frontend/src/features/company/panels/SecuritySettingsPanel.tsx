import { useState } from 'react'
import { Alert, Button, Card, CardContent, Stack, TextField, Typography } from '@mui/material'
import { extractErrorMessage } from '../../../shared/api/errors'
import { useUpdateCompanyMutation } from '../api'
import type { Company } from '../types'

const MIN_ALLOWED = 10
const MAX_ALLOWED = 72

export function SecuritySettingsPanel({ company }: { company: Company }) {
  const savedValue = company.settings.security?.min_password_length ?? MIN_ALLOWED
  const [minPasswordLength, setMinPasswordLength] = useState(savedValue)
  const updateMutation = useUpdateCompanyMutation()

  const isValid = minPasswordLength >= MIN_ALLOWED && minPasswordLength <= MAX_ALLOWED
  const isDirty = minPasswordLength !== savedValue

  return (
    <Card variant="outlined" sx={{ maxWidth: 520 }}>
      <CardContent>
        <Stack spacing={2}>
          <Typography variant="body2" color="text.secondary">
            Every password on the platform already requires at least {MIN_ALLOWED} characters with a
            letter and a digit. Raise the minimum length further for your company here.
          </Typography>

          {updateMutation.isError && (
            <Alert severity="error">{extractErrorMessage(updateMutation.error)}</Alert>
          )}
          {updateMutation.isSuccess && !isDirty && <Alert severity="success">Saved.</Alert>}

          <TextField
            label="Minimum password length"
            type="number"
            value={minPasswordLength}
            onChange={(event) => setMinPasswordLength(Number(event.target.value))}
            slotProps={{ htmlInput: { min: MIN_ALLOWED, max: MAX_ALLOWED } }}
            error={!isValid}
            helperText={!isValid ? `Must be between ${MIN_ALLOWED} and ${MAX_ALLOWED}` : ' '}
            sx={{ maxWidth: 280 }}
          />

          <Button
            variant="contained"
            disabled={updateMutation.isPending || !isValid || !isDirty}
            onClick={() =>
              updateMutation.mutate({
                settings: { security: { min_password_length: minPasswordLength } },
              })
            }
            sx={{ alignSelf: 'flex-start' }}
          >
            {updateMutation.isPending ? 'Saving…' : 'Save changes'}
          </Button>
        </Stack>
      </CardContent>
    </Card>
  )
}

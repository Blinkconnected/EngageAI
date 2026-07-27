import { useState } from 'react'
import { Alert, Button, Card, CardContent, Stack, TextField, Typography } from '@mui/material'
import { useTranslation } from 'react-i18next'
import { extractErrorMessage } from '../../../shared/api/errors'
import { useUpdateCompanyMutation } from '../api'
import type { Company } from '../types'

const MIN_ALLOWED = 10
const MAX_ALLOWED = 72

export function SecuritySettingsPanel({ company }: { company: Company }) {
  const { t } = useTranslation('companySettingsExtra')
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
            {t('SecuritySettingsPanel.description', { minAllowed: MIN_ALLOWED })}
          </Typography>

          {updateMutation.isError && (
            <Alert severity="error">{extractErrorMessage(updateMutation.error)}</Alert>
          )}
          {updateMutation.isSuccess && !isDirty && (
            <Alert severity="success">{t('SecuritySettingsPanel.savedAlert')}</Alert>
          )}

          <TextField
            label={t('SecuritySettingsPanel.minPasswordLengthLabel')}
            type="number"
            value={minPasswordLength}
            onChange={(event) => setMinPasswordLength(Number(event.target.value))}
            slotProps={{ htmlInput: { min: MIN_ALLOWED, max: MAX_ALLOWED } }}
            error={!isValid}
            helperText={
              !isValid
                ? t('SecuritySettingsPanel.minPasswordLengthHelperError', {
                    min: MIN_ALLOWED,
                    max: MAX_ALLOWED,
                  })
                : ' '
            }
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
            {updateMutation.isPending
              ? t('SecuritySettingsPanel.savingButton')
              : t('SecuritySettingsPanel.saveButton')}
          </Button>
        </Stack>
      </CardContent>
    </Card>
  )
}

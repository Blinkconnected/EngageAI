import { useState } from 'react'
import {
  Alert,
  Avatar,
  Box,
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

export function BrandingSettingsPanel({ company }: { company: Company }) {
  const { t } = useTranslation('companySettings')
  const [logoUrl, setLogoUrl] = useState(company.settings.branding?.logo_url ?? '')
  const updateMutation = useUpdateCompanyMutation()
  const savedLogoUrl = company.settings.branding?.logo_url ?? ''
  const isDirty = logoUrl !== savedLogoUrl

  function handleSave() {
    updateMutation.mutate({ settings: { branding: { logo_url: logoUrl || null } } })
  }

  return (
    <Card variant="outlined" sx={{ maxWidth: 520 }}>
      <CardContent>
        <Stack spacing={2}>
          <Typography variant="body2" color="text.secondary">
            {t('BrandingSettingsPanel.description')}
          </Typography>

          {updateMutation.isError && (
            <Alert severity="error">{extractErrorMessage(updateMutation.error)}</Alert>
          )}
          {updateMutation.isSuccess && !isDirty && (
            <Alert severity="success">{t('BrandingSettingsPanel.savedMessage')}</Alert>
          )}

          <Stack direction="row" spacing={2} sx={{ alignItems: 'center' }}>
            <Avatar
              variant="rounded"
              src={logoUrl || undefined}
              alt={t('BrandingSettingsPanel.logoPreviewAlt')}
              sx={{ width: 56, height: 56, bgcolor: 'action.hover' }}
            >
              {company.name.charAt(0).toUpperCase()}
            </Avatar>
            <Box sx={{ flexGrow: 1 }}>
              <TextField
                label={t('BrandingSettingsPanel.logoUrlLabel')}
                value={logoUrl}
                onChange={(event) => setLogoUrl(event.target.value)}
                fullWidth
                placeholder={t('BrandingSettingsPanel.logoUrlPlaceholder')}
              />
            </Box>
          </Stack>

          <Stack direction="row" spacing={2}>
            <Button
              variant="contained"
              disabled={updateMutation.isPending || !isDirty}
              onClick={handleSave}
            >
              {updateMutation.isPending
                ? t('BrandingSettingsPanel.savingButton')
                : t('BrandingSettingsPanel.saveChangesButton')}
            </Button>
            {savedLogoUrl && (
              <Button
                color="error"
                variant="outlined"
                disabled={updateMutation.isPending}
                onClick={() => {
                  setLogoUrl('')
                  updateMutation.mutate({ settings: { branding: { logo_url: null } } })
                }}
              >
                {t('BrandingSettingsPanel.removeLogoButton')}
              </Button>
            )}
          </Stack>
        </Stack>
      </CardContent>
    </Card>
  )
}

import { useRef, type ChangeEvent } from 'react'
import { Alert, Avatar, Button, Card, CardContent, Stack, Typography } from '@mui/material'
import { useTranslation } from 'react-i18next'
import { extractErrorMessage } from '../../../shared/api/errors'
import {
  useCompanyLogoUrl,
  useDeleteCompanyLogoMutation,
  useUploadCompanyLogoMutation,
} from '../api'
import type { Company } from '../types'

const ACCEPTED_TYPES = 'image/png,image/jpeg,image/webp'

export function BrandingSettingsPanel({ company }: { company: Company }) {
  const { t } = useTranslation('companySettings')
  const fileInputRef = useRef<HTMLInputElement>(null)
  const logoKey = company.settings.branding?.logo_key
  const logoUrlQuery = useCompanyLogoUrl(logoKey)
  const uploadMutation = useUploadCompanyLogoMutation()
  const deleteMutation = useDeleteCompanyLogoMutation()

  function handleFileSelected(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    // Reset so choosing the exact same file again still fires onChange.
    event.target.value = ''
    if (file) uploadMutation.mutate(file)
  }

  return (
    <Card variant="outlined" sx={{ maxWidth: 520 }}>
      <CardContent>
        <Stack spacing={2}>
          <Typography variant="body2" color="text.secondary">
            {t('BrandingSettingsPanel.description')}
          </Typography>

          {(uploadMutation.isError || deleteMutation.isError) && (
            <Alert severity="error">
              {extractErrorMessage(uploadMutation.error ?? deleteMutation.error)}
            </Alert>
          )}
          {uploadMutation.isSuccess && (
            <Alert severity="success">{t('BrandingSettingsPanel.uploadedMessage')}</Alert>
          )}
          {deleteMutation.isSuccess && (
            <Alert severity="success">{t('BrandingSettingsPanel.removedMessage')}</Alert>
          )}

          <Stack direction="row" spacing={2} sx={{ alignItems: 'center' }}>
            <Avatar
              variant="rounded"
              src={logoUrlQuery.data}
              alt={t('BrandingSettingsPanel.logoPreviewAlt')}
              sx={{ width: 56, height: 56, bgcolor: 'action.hover' }}
            >
              {company.name.charAt(0).toUpperCase()}
            </Avatar>

            <input
              ref={fileInputRef}
              type="file"
              hidden
              accept={ACCEPTED_TYPES}
              onChange={handleFileSelected}
            />
            <Button
              variant="outlined"
              disabled={uploadMutation.isPending}
              onClick={() => fileInputRef.current?.click()}
            >
              {uploadMutation.isPending
                ? t('BrandingSettingsPanel.uploadingButton')
                : logoKey
                  ? t('BrandingSettingsPanel.changeButton')
                  : t('BrandingSettingsPanel.uploadButton')}
            </Button>
            {logoKey && (
              <Button
                color="error"
                variant="outlined"
                disabled={deleteMutation.isPending}
                onClick={() => deleteMutation.mutate()}
              >
                {deleteMutation.isPending
                  ? t('BrandingSettingsPanel.removingButton')
                  : t('BrandingSettingsPanel.removeLogoButton')}
              </Button>
            )}
          </Stack>

          <Typography variant="caption" color="text.secondary">
            {t('BrandingSettingsPanel.helperText')}
          </Typography>
        </Stack>
      </CardContent>
    </Card>
  )
}

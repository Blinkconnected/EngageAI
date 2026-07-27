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
import { extractErrorMessage } from '../../../shared/api/errors'
import { useUpdateCompanyMutation } from '../api'
import type { Company } from '../types'

export function BrandingSettingsPanel({ company }: { company: Company }) {
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
            Shown in the header next to your company name. Paste a link to an image already hosted
            elsewhere (your website, a CDN, etc.).
          </Typography>

          {updateMutation.isError && (
            <Alert severity="error">{extractErrorMessage(updateMutation.error)}</Alert>
          )}
          {updateMutation.isSuccess && !isDirty && <Alert severity="success">Saved.</Alert>}

          <Stack direction="row" spacing={2} sx={{ alignItems: 'center' }}>
            <Avatar
              variant="rounded"
              src={logoUrl || undefined}
              alt="Logo preview"
              sx={{ width: 56, height: 56, bgcolor: 'action.hover' }}
            >
              {company.name.charAt(0).toUpperCase()}
            </Avatar>
            <Box sx={{ flexGrow: 1 }}>
              <TextField
                label="Logo URL"
                value={logoUrl}
                onChange={(event) => setLogoUrl(event.target.value)}
                fullWidth
                placeholder="https://cdn.example.com/logo.png"
              />
            </Box>
          </Stack>

          <Stack direction="row" spacing={2}>
            <Button
              variant="contained"
              disabled={updateMutation.isPending || !isDirty}
              onClick={handleSave}
            >
              {updateMutation.isPending ? 'Saving…' : 'Save changes'}
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
                Remove logo
              </Button>
            )}
          </Stack>
        </Stack>
      </CardContent>
    </Card>
  )
}

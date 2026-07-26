import { useState, type FormEvent } from 'react'
import { Alert, Button, Card, CardContent, Chip, Stack, TextField, Typography } from '@mui/material'
import { extractErrorMessage } from '../../../shared/api/errors'
import { useUpdateCompanyMutation } from '../api'
import type { Company } from '../types'

const STATUS_COLOR = {
  trial: 'info',
  active: 'success',
  suspended: 'error',
} as const

export function GeneralSettingsPanel({ company }: { company: Company }) {
  const [name, setName] = useState(company.name)
  const updateMutation = useUpdateCompanyMutation()

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    updateMutation.mutate({ name })
  }

  return (
    <Card variant="outlined" sx={{ maxWidth: 520 }}>
      <CardContent>
        <Stack spacing={2} component="form" onSubmit={handleSubmit}>
          <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
            <Typography variant="body2" color="text.secondary">
              {company.slug}
            </Typography>
            <Chip label={company.status} size="small" color={STATUS_COLOR[company.status]} />
          </Stack>

          {updateMutation.isError && (
            <Alert severity="error">{extractErrorMessage(updateMutation.error)}</Alert>
          )}
          {updateMutation.isSuccess && <Alert severity="success">Saved.</Alert>}

          <TextField
            label="Company name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            required
            fullWidth
          />
          <Button
            type="submit"
            variant="contained"
            disabled={updateMutation.isPending || name === company.name}
            sx={{ alignSelf: 'flex-start' }}
          >
            {updateMutation.isPending ? 'Saving…' : 'Save changes'}
          </Button>
        </Stack>
      </CardContent>
    </Card>
  )
}

import { useState, type FormEvent } from 'react'
import { Link as RouterLink, Navigate, useNavigate } from 'react-router-dom'
import { Alert, Box, Button, Link, Paper, Stack, TextField, Typography } from '@mui/material'
import { useAppSelector } from '../../app/hooks'
import { extractErrorMessage } from '../../shared/api/errors'
import { selectIsAuthenticated } from './authSlice'
import { useRegisterMutation } from './api'

export function RegisterPage() {
  const [companyName, setCompanyName] = useState('')
  const [ownerFullName, setOwnerFullName] = useState('')
  const [ownerEmail, setOwnerEmail] = useState('')
  const [ownerPassword, setOwnerPassword] = useState('')
  const isAuthenticated = useAppSelector(selectIsAuthenticated)
  const navigate = useNavigate()
  const registerMutation = useRegisterMutation()

  if (isAuthenticated) {
    return <Navigate to="/" replace />
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    registerMutation.mutate(
      {
        company_name: companyName,
        owner_full_name: ownerFullName,
        owner_email: ownerEmail,
        owner_password: ownerPassword,
      },
      { onSuccess: () => navigate('/onboarding', { replace: true }) },
    )
  }

  return (
    <Box
      sx={{
        minHeight: '100%',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        bgcolor: 'background.default',
        p: 2,
      }}
    >
      <Paper component="form" onSubmit={handleSubmit} elevation={2} sx={{ p: 4, width: 440 }}>
        <Stack spacing={2}>
          <Typography variant="h5" component="h1" sx={{ fontWeight: 600 }}>
            Create your company
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Set up your Blink Engage workspace. You'll be signed in as the owner immediately.
          </Typography>

          {registerMutation.isError && (
            <Alert severity="error" data-testid="register-error">
              {extractErrorMessage(
                registerMutation.error,
                'Could not create your company. Please check your details and try again.',
              )}
            </Alert>
          )}

          <TextField
            label="Company name"
            value={companyName}
            onChange={(event) => setCompanyName(event.target.value)}
            required
            fullWidth
            autoComplete="organization"
          />
          <TextField
            label="Your full name"
            value={ownerFullName}
            onChange={(event) => setOwnerFullName(event.target.value)}
            required
            fullWidth
            autoComplete="name"
          />
          <TextField
            label="Email"
            type="email"
            value={ownerEmail}
            onChange={(event) => setOwnerEmail(event.target.value)}
            required
            fullWidth
            autoComplete="email"
          />
          <TextField
            label="Password"
            type="password"
            value={ownerPassword}
            onChange={(event) => setOwnerPassword(event.target.value)}
            required
            fullWidth
            autoComplete="new-password"
            helperText="At least 10 characters, including a letter and a digit."
          />
          <Button
            type="submit"
            variant="contained"
            size="large"
            fullWidth
            disabled={registerMutation.isPending}
          >
            {registerMutation.isPending ? 'Creating your company…' : 'Create company'}
          </Button>
          <Typography variant="body2" color="text.secondary" sx={{ textAlign: 'center' }}>
            Already have a workspace?{' '}
            <Link component={RouterLink} to="/login">
              Sign in
            </Link>
          </Typography>
        </Stack>
      </Paper>
    </Box>
  )
}

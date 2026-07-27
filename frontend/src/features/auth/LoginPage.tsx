import { useState, type FormEvent } from 'react'
import { Link as RouterLink, Navigate, useLocation } from 'react-router-dom'
import { Alert, Box, Button, Link, Paper, Stack, TextField, Typography } from '@mui/material'
import { useTranslation } from 'react-i18next'
import { useAppSelector } from '../../app/hooks'
import { extractErrorMessage } from '../../shared/api/errors'
import { Footer } from '../../shared/components/Footer'
import logoLight from '../../assets/logo-light.png'
import { selectIsAuthenticated } from './authSlice'
import { useLoginMutation } from './api'

export function LoginPage() {
  const { t } = useTranslation('auth')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const isAuthenticated = useAppSelector(selectIsAuthenticated)
  const location = useLocation()
  const loginMutation = useLoginMutation()

  if (isAuthenticated) {
    const from = (location.state as { from?: Location })?.from?.pathname ?? '/'
    return <Navigate to={from} replace />
  }

  const flashMessage = (location.state as { message?: string } | null)?.message

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    loginMutation.mutate({ email, password })
  }

  return (
    <Box
      sx={{
        minHeight: '100%',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        bgcolor: 'background.default',
        p: 2,
      }}
    >
      <Paper component="form" onSubmit={handleSubmit} elevation={2} sx={{ p: 4, width: 400 }}>
        <Stack spacing={2}>
          <Box
            component="img"
            src={logoLight}
            alt={t('LoginPage.logoAlt')}
            sx={{ height: 80, width: 'auto', display: 'block', mx: 'auto', alignSelf: 'center' }}
          />
          <Typography
            variant="body2"
            component="h1"
            color="text.secondary"
            sx={{ textAlign: 'center' }}
          >
            {t('LoginPage.subtitle')}
          </Typography>

          {!loginMutation.isError && flashMessage && (
            <Alert severity="info" data-testid="login-flash-message">
              {flashMessage}
            </Alert>
          )}

          {loginMutation.isError && (
            <Alert severity="error" data-testid="login-error">
              {extractErrorMessage(loginMutation.error, t('LoginPage.invalidCredentials'))}
            </Alert>
          )}

          <TextField
            label={t('LoginPage.emailLabel')}
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            required
            fullWidth
            autoComplete="username"
          />
          <TextField
            label={t('LoginPage.passwordLabel')}
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
            fullWidth
            autoComplete="current-password"
          />
          <Button
            type="submit"
            variant="contained"
            size="large"
            fullWidth
            disabled={loginMutation.isPending}
          >
            {loginMutation.isPending ? t('LoginPage.signingIn') : t('LoginPage.signIn')}
          </Button>
          <Typography variant="body2" color="text.secondary" sx={{ textAlign: 'center' }}>
            {t('LoginPage.newToBlinkEngage')}{' '}
            <Link component={RouterLink} to="/register">
              {t('LoginPage.createYourCompanyLink')}
            </Link>
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ textAlign: 'center' }}>
            <Link component={RouterLink} to="/changelog">
              {t('LoginPage.whatsNewLink')}
            </Link>
          </Typography>
        </Stack>
      </Paper>
      <Footer />
    </Box>
  )
}

import { useState, type FormEvent } from 'react'
import { Link as RouterLink, Navigate, useLocation } from 'react-router-dom'
import { Alert, Box, Button, Link, Paper, Stack, TextField, Typography } from '@mui/material'
import { useAppSelector } from '../../app/hooks'
import { extractErrorMessage } from '../../shared/api/errors'
import { Footer } from '../../shared/components/Footer'
import logoLight from '../../assets/logo-light.png'
import { selectIsAuthenticated } from './authSlice'
import { useLoginMutation } from './api'

export function LoginPage() {
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
            alt="Blink Engage"
            sx={{ height: 40, width: 'auto', display: 'block', mx: 'auto' }}
          />
          <Typography variant="body2" color="text.secondary">
            Sign in to your workspace
          </Typography>

          {!loginMutation.isError && flashMessage && (
            <Alert severity="info" data-testid="login-flash-message">
              {flashMessage}
            </Alert>
          )}

          {loginMutation.isError && (
            <Alert severity="error" data-testid="login-error">
              {extractErrorMessage(loginMutation.error, 'Invalid email or password.')}
            </Alert>
          )}

          <TextField
            label="Email"
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            required
            fullWidth
            autoComplete="username"
          />
          <TextField
            label="Password"
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
            {loginMutation.isPending ? 'Signing in…' : 'Sign in'}
          </Button>
          <Typography variant="body2" color="text.secondary" sx={{ textAlign: 'center' }}>
            New to Blink Engage?{' '}
            <Link component={RouterLink} to="/register">
              Create your company
            </Link>
          </Typography>
        </Stack>
      </Paper>
      <Footer />
    </Box>
  )
}

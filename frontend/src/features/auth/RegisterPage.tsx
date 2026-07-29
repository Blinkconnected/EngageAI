import { useState, type FormEvent } from 'react'
import { Link as RouterLink, Navigate, useNavigate } from 'react-router-dom'
import {
  Alert,
  Box,
  Button,
  Link,
  MenuItem,
  Paper,
  Stack,
  TextField,
  Typography,
} from '@mui/material'
import { useTranslation } from 'react-i18next'
import { useAppSelector } from '../../app/hooks'
import { extractErrorMessage } from '../../shared/api/errors'
import { Footer } from '../../shared/components/Footer'
import logoLight from '../../assets/logo-light.png'
import { selectIsAuthenticated } from './authSlice'
import { useCountriesQuery, useRegisterMutation } from './api'

export function RegisterPage() {
  const { t } = useTranslation('auth')
  const [companyName, setCompanyName] = useState('')
  const [ownerFullName, setOwnerFullName] = useState('')
  const [ownerEmail, setOwnerEmail] = useState('')
  const [ownerPassword, setOwnerPassword] = useState('')
  const [countryCode, setCountryCode] = useState('')
  const countriesQuery = useCountriesQuery()
  const isAuthenticated = useAppSelector(selectIsAuthenticated)
  const navigate = useNavigate()
  const registerMutation = useRegisterMutation()

  if (isAuthenticated) {
    return <Navigate to="/" replace />
  }

  const selectedCountry = (countriesQuery.data ?? []).find(
    (country) => country.code === countryCode,
  )

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    registerMutation.mutate(
      {
        company_name: companyName,
        owner_full_name: ownerFullName,
        owner_email: ownerEmail,
        owner_password: ownerPassword,
        // Omitted rather than sent empty: the backend treats an absent
        // country as "not recorded", while an empty string is a value it
        // would have to reject.
        ...(countryCode ? { country_code: countryCode } : {}),
      },
      { onSuccess: () => navigate('/onboarding', { replace: true }) },
    )
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
      <Paper
        component="form"
        onSubmit={handleSubmit}
        elevation={2}
        sx={{ p: 4, width: 440, maxWidth: '100%' }}
      >
        <Stack spacing={2}>
          <Box
            component="img"
            src={logoLight}
            alt={t('RegisterPage.logoAlt')}
            sx={{ height: 80, width: 'auto', display: 'block', mx: 'auto', alignSelf: 'center' }}
          />
          <Typography variant="h5" component="h1" sx={{ fontWeight: 600, textAlign: 'center' }}>
            {t('RegisterPage.title')}
          </Typography>
          <Typography variant="body2" color="text.secondary">
            {t('RegisterPage.subtitle')}
          </Typography>

          {registerMutation.isError && (
            <Alert severity="error" data-testid="register-error">
              {extractErrorMessage(registerMutation.error, t('RegisterPage.createCompanyError'))}
            </Alert>
          )}

          <TextField
            label={t('RegisterPage.companyNameLabel')}
            value={companyName}
            onChange={(event) => setCompanyName(event.target.value)}
            required
            fullWidth
            autoComplete="organization"
          />
          <TextField
            label={t('RegisterPage.fullNameLabel')}
            value={ownerFullName}
            onChange={(event) => setOwnerFullName(event.target.value)}
            required
            fullWidth
            autoComplete="name"
          />
          <TextField
            label={t('RegisterPage.emailLabel')}
            type="email"
            value={ownerEmail}
            onChange={(event) => setOwnerEmail(event.target.value)}
            required
            fullWidth
            autoComplete="email"
          />
          <TextField
            select
            label={t('RegisterPage.countryLabel')}
            value={countryCode}
            onChange={(event) => setCountryCode(event.target.value)}
            required
            fullWidth
            disabled={countriesQuery.isPending}
            // Says which currency they will be billed in *before* they
            // sign up: it cannot be changed afterwards, so it must not be
            // a surprise on the first invoice.
            helperText={
              selectedCountry
                ? t('RegisterPage.countryCurrencyHelp', {
                    currency: selectedCountry.currency,
                  })
                : t('RegisterPage.countryHelp')
            }
          >
            {(countriesQuery.data ?? []).map((country) => (
              <MenuItem key={country.code} value={country.code}>
                {country.name}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            label={t('RegisterPage.passwordLabel')}
            type="password"
            value={ownerPassword}
            onChange={(event) => setOwnerPassword(event.target.value)}
            required
            fullWidth
            autoComplete="new-password"
            helperText={t('RegisterPage.passwordHelperText')}
          />
          <Button
            type="submit"
            variant="contained"
            size="large"
            fullWidth
            disabled={registerMutation.isPending}
          >
            {registerMutation.isPending
              ? t('RegisterPage.creatingCompany')
              : t('RegisterPage.createCompany')}
          </Button>
          <Typography variant="body2" color="text.secondary" sx={{ textAlign: 'center' }}>
            {t('RegisterPage.alreadyHaveWorkspace')}{' '}
            <Link component={RouterLink} to="/login">
              {t('RegisterPage.signInLink')}
            </Link>
          </Typography>
        </Stack>
      </Paper>
      <Footer />
    </Box>
  )
}

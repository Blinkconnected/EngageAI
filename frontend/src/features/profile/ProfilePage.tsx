import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Divider,
  Paper,
  Stack,
  TextField,
  Typography,
} from '@mui/material'
import { useTranslation } from 'react-i18next'
import { PageHeader } from '../../shared/components/PageHeader'
import { extractErrorMessage } from '../../shared/api/errors'
import { useLogout } from '../auth/api'
import { useCurrentUserQuery } from '../session/api'
import { useChangePasswordMutation } from './api'

export function ProfilePage() {
  const { t } = useTranslation('profile')
  const { data: currentUser } = useCurrentUserQuery()
  const navigate = useNavigate()
  const logout = useLogout()
  const changePasswordMutation = useChangePasswordMutation()

  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [mismatchError, setMismatchError] = useState(false)

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    if (newPassword !== confirmPassword) {
      setMismatchError(true)
      return
    }
    setMismatchError(false)
    changePasswordMutation.mutate(
      { current_password: currentPassword, new_password: newPassword },
      {
        onSuccess: async () => {
          await logout()
          navigate('/login', {
            replace: true,
            state: { message: t('ProfilePage.passwordChangedMessage') },
          })
        },
      },
    )
  }

  return (
    <>
      <PageHeader
        title={t('ProfilePage.pageTitle')}
        description={t('ProfilePage.pageDescription')}
      />

      <Stack spacing={3} sx={{ maxWidth: 480 }}>
        {currentUser && (
          <Card variant="outlined">
            <CardContent>
              <Stack spacing={0.5}>
                <Typography variant="subtitle1" component="div" sx={{ fontWeight: 600 }}>
                  {currentUser.full_name}
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  {currentUser.email}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  {currentUser.roles.join(', ')} · {currentUser.company.name}
                </Typography>
              </Stack>
            </CardContent>
          </Card>
        )}

        <Paper component="form" onSubmit={handleSubmit} variant="outlined" sx={{ p: 3 }}>
          <Stack spacing={2}>
            <Box>
              <Typography variant="subtitle1" component="div" sx={{ fontWeight: 600 }}>
                {t('ProfilePage.changePasswordHeading')}
              </Typography>
              <Typography variant="body2" color="text.secondary">
                {t('ProfilePage.changePasswordDescription')}
              </Typography>
            </Box>
            <Divider />

            {changePasswordMutation.isError && (
              <Alert severity="error">
                {extractErrorMessage(
                  changePasswordMutation.error,
                  t('ProfilePage.changePasswordErrorFallback'),
                )}
              </Alert>
            )}
            {mismatchError && (
              <Alert severity="error">{t('ProfilePage.passwordMismatchError')}</Alert>
            )}

            <TextField
              label={t('ProfilePage.currentPasswordLabel')}
              type="password"
              value={currentPassword}
              onChange={(event) => setCurrentPassword(event.target.value)}
              required
              fullWidth
              autoComplete="current-password"
            />
            <TextField
              label={t('ProfilePage.newPasswordLabel')}
              type="password"
              value={newPassword}
              onChange={(event) => setNewPassword(event.target.value)}
              required
              fullWidth
              autoComplete="new-password"
              helperText={t('ProfilePage.newPasswordHelperText')}
            />
            <TextField
              label={t('ProfilePage.confirmPasswordLabel')}
              type="password"
              value={confirmPassword}
              onChange={(event) => setConfirmPassword(event.target.value)}
              required
              fullWidth
              autoComplete="new-password"
            />
            <Box>
              <Button type="submit" variant="contained" disabled={changePasswordMutation.isPending}>
                {changePasswordMutation.isPending
                  ? t('ProfilePage.changingButton')
                  : t('ProfilePage.changePasswordButton')}
              </Button>
            </Box>
          </Stack>
        </Paper>
      </Stack>
    </>
  )
}

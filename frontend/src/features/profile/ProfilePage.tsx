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
import { PageHeader } from '../../shared/components/PageHeader'
import { extractErrorMessage } from '../../shared/api/errors'
import { useLogout } from '../auth/api'
import { useCurrentUserQuery } from '../session/api'
import { useChangePasswordMutation } from './api'

export function ProfilePage() {
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
            state: { message: 'Password changed. Please sign in with your new password.' },
          })
        },
      },
    )
  }

  return (
    <>
      <PageHeader title="My Profile" description="Your account details and security settings." />

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
                Change password
              </Typography>
              <Typography variant="body2" color="text.secondary">
                You'll be signed out of every device and need to sign in again.
              </Typography>
            </Box>
            <Divider />

            {changePasswordMutation.isError && (
              <Alert severity="error">
                {extractErrorMessage(changePasswordMutation.error, 'Could not change password.')}
              </Alert>
            )}
            {mismatchError && <Alert severity="error">New passwords do not match.</Alert>}

            <TextField
              label="Current password"
              type="password"
              value={currentPassword}
              onChange={(event) => setCurrentPassword(event.target.value)}
              required
              fullWidth
              autoComplete="current-password"
            />
            <TextField
              label="New password"
              type="password"
              value={newPassword}
              onChange={(event) => setNewPassword(event.target.value)}
              required
              fullWidth
              autoComplete="new-password"
              helperText="At least 10 characters, including a letter and a digit."
            />
            <TextField
              label="Confirm new password"
              type="password"
              value={confirmPassword}
              onChange={(event) => setConfirmPassword(event.target.value)}
              required
              fullWidth
              autoComplete="new-password"
            />
            <Box>
              <Button type="submit" variant="contained" disabled={changePasswordMutation.isPending}>
                {changePasswordMutation.isPending ? 'Changing…' : 'Change password'}
              </Button>
            </Box>
          </Stack>
        </Paper>
      </Stack>
    </>
  )
}

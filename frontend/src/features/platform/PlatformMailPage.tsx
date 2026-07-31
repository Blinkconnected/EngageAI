import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import Alert from '@mui/material/Alert'
import Box from '@mui/material/Box'
import Button from '@mui/material/Button'
import Card from '@mui/material/Card'
import CardContent from '@mui/material/CardContent'
import Chip from '@mui/material/Chip'
import CircularProgress from '@mui/material/CircularProgress'
import MenuItem from '@mui/material/MenuItem'
import Stack from '@mui/material/Stack'
import TextField from '@mui/material/TextField'
import Typography from '@mui/material/Typography'

import {
  useMailSettingsQuery,
  useResetMailSettingsMutation,
  useSaveMailSettingsMutation,
  useTestMailMutation,
} from './api'
import type { MailSecurity, MailSettingsInput } from './types'

/** Conventional ports, offered when the security mode changes so an
 * operator picking STARTTLS does not have to remember 587. A hint, not
 * a constraint — a relay on a non-standard port is perfectly normal, so
 * this only fills the field when it still holds another mode's default. */
const DEFAULT_PORTS: Record<MailSecurity, number> = {
  tls: 465,
  starttls: 587,
  none: 25,
}

const SECURITY_MODES: MailSecurity[] = ['starttls', 'tls', 'none']

interface FormState {
  host: string
  port: string
  security: MailSecurity
  fromAddress: string
  fromName: string
  username: string
  password: string
  timeoutSeconds: string
}

export function PlatformMailPage() {
  const { t } = useTranslation('platform')
  const settingsQuery = useMailSettingsQuery()
  const save = useSaveMailSettingsMutation()
  const reset = useResetMailSettingsMutation()
  const test = useTestMailMutation()

  /** Edits held as an *overlay* on the loaded settings rather than
   * copied into state by an effect. Copying would need a
   * setState-in-effect to resync whenever the server sends new values
   * (after a save, or a reset), which triggers a cascading render — and
   * would silently drop an edit made while the request was in flight. */
  const [edits, setEdits] = useState<Partial<FormState>>({})
  const [testAddress, setTestAddress] = useState('')

  const settings = settingsQuery.data

  if (settingsQuery.isPending || !settings) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', p: 4 }}>
        <CircularProgress />
      </Box>
    )
  }

  if (settingsQuery.isError) {
    return <Alert severity="error">{t('PlatformMailPage.loadFailed')}</Alert>
  }

  const form: FormState = {
    host: settings.host,
    port: String(settings.port),
    security: settings.security,
    fromAddress: settings.from_address,
    fromName: settings.from_name,
    username: settings.username ?? '',
    password: '',
    timeoutSeconds: String(settings.timeout_seconds),
    ...edits,
  }

  /** An empty password field means "leave the stored one alone" until
   * the operator actually types in it. Sending "" unconditionally would
   * clear a working password every time somebody edited the host. */
  const passwordTouched = edits.password !== undefined

  const update = (patch: Partial<FormState>) => setEdits({ ...edits, ...patch })

  const changeSecurity = (security: MailSecurity) => {
    const currentPort = Number(form.port)
    const wasDefaultPort = Object.values(DEFAULT_PORTS).includes(currentPort)
    update({
      security,
      // Only overwrite a port the operator has not chosen themselves.
      port: wasDefaultPort ? String(DEFAULT_PORTS[security]) : form.port,
    })
  }

  const handleSave = () => {
    const input: MailSettingsInput = {
      host: form.host.trim(),
      port: Number(form.port),
      security: form.security,
      from_address: form.fromAddress.trim(),
      from_name: form.fromName.trim(),
      username: form.username.trim() || null,
      timeout_seconds: Number(form.timeoutSeconds),
    }
    // Omitted entirely unless typed in — see `passwordTouched`.
    if (passwordTouched) input.password = form.password
    save.mutate(input, { onSuccess: () => setEdits({}) })
  }

  const testResult = test.data

  return (
    <Stack spacing={3} sx={{ maxWidth: 720 }}>
      <Box>
        <Typography variant="h5" sx={{ fontWeight: 700 }}>
          {t('PlatformMailPage.title')}
        </Typography>
        <Typography variant="body2" color="text.secondary">
          {t('PlatformMailPage.subtitle')}
        </Typography>
      </Box>

      {!settings?.customised && (
        <Alert severity="info">{t('PlatformMailPage.usingEnvironment')}</Alert>
      )}

      <Card variant="outlined">
        <CardContent>
          <Stack spacing={2.5}>
            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
              <TextField
                label={t('PlatformMailPage.host')}
                value={form.host}
                onChange={(e) => update({ host: e.target.value })}
                fullWidth
                required
              />
              <TextField
                label={t('PlatformMailPage.port')}
                value={form.port}
                onChange={(e) => update({ port: e.target.value })}
                type="number"
                sx={{ width: { sm: 140 } }}
                required
              />
            </Stack>

            <TextField
              select
              label={t('PlatformMailPage.security')}
              value={form.security}
              onChange={(e) => changeSecurity(e.target.value as MailSecurity)}
              helperText={t(`PlatformMailPage.securityHelp.${form.security}`)}
              fullWidth
            >
              {SECURITY_MODES.map((mode) => (
                <MenuItem key={mode} value={mode}>
                  {t(`PlatformMailPage.securityMode.${mode}`)}
                </MenuItem>
              ))}
            </TextField>

            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
              <TextField
                label={t('PlatformMailPage.fromName')}
                value={form.fromName}
                onChange={(e) => update({ fromName: e.target.value })}
                fullWidth
                required
              />
              <TextField
                label={t('PlatformMailPage.fromAddress')}
                value={form.fromAddress}
                onChange={(e) => update({ fromAddress: e.target.value })}
                type="email"
                fullWidth
                required
              />
            </Stack>

            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
              <TextField
                label={t('PlatformMailPage.username')}
                value={form.username}
                onChange={(e) => update({ username: e.target.value })}
                fullWidth
              />
              <TextField
                label={t('PlatformMailPage.password')}
                value={form.password}
                onChange={(e) => update({ password: e.target.value })}
                type="password"
                fullWidth
                placeholder={
                  settings?.password_set
                    ? t('PlatformMailPage.passwordSet')
                    : t('PlatformMailPage.passwordNone')
                }
                helperText={
                  passwordTouched
                    ? t('PlatformMailPage.passwordWillChange')
                    : t('PlatformMailPage.passwordUnchanged')
                }
              />
            </Stack>

            {settings?.updated_by_email && (
              <Typography variant="caption" color="text.secondary">
                {t('PlatformMailPage.lastChanged', {
                  email: settings.updated_by_email,
                  when: settings.updated_at ? new Date(settings.updated_at).toLocaleString() : '',
                })}
              </Typography>
            )}

            <Stack direction="row" spacing={1.5} sx={{ alignItems: 'center' }}>
              <Button variant="contained" onClick={handleSave} disabled={save.isPending}>
                {t('PlatformMailPage.save')}
              </Button>
              {settings?.customised && (
                <Button
                  color="inherit"
                  onClick={() => reset.mutate(undefined, { onSuccess: () => setEdits({}) })}
                  disabled={reset.isPending}
                >
                  {t('PlatformMailPage.reset')}
                </Button>
              )}
              {save.isSuccess && !save.isPending && (
                <Chip size="small" color="success" label={t('PlatformMailPage.saved')} />
              )}
            </Stack>
            {save.isError && <Alert severity="error">{t('PlatformMailPage.saveFailed')}</Alert>}
          </Stack>
        </CardContent>
      </Card>

      <Card variant="outlined">
        <CardContent>
          <Stack spacing={2}>
            <Box>
              <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
                {t('PlatformMailPage.testTitle')}
              </Typography>
              <Typography variant="body2" color="text.secondary">
                {t('PlatformMailPage.testSubtitle')}
              </Typography>
            </Box>
            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
              <TextField
                label={t('PlatformMailPage.testAddress')}
                value={testAddress}
                onChange={(e) => setTestAddress(e.target.value)}
                type="email"
                fullWidth
              />
              <Button
                variant="outlined"
                onClick={() => test.mutate(testAddress.trim())}
                disabled={!testAddress.trim() || test.isPending}
                sx={{ whiteSpace: 'nowrap' }}
              >
                {t('PlatformMailPage.sendTest')}
              </Button>
            </Stack>
            {testResult && (
              <Alert severity={testResult.delivered ? 'success' : 'error'}>
                {testResult.delivered
                  ? t('PlatformMailPage.testDelivered')
                  : // The relay's own words: "535 authentication failed"
                    // tells an operator to fix the password, while a
                    // generic failure sends them looking at DNS.
                    t('PlatformMailPage.testFailed', { detail: testResult.detail ?? '' })}
              </Alert>
            )}
          </Stack>
        </CardContent>
      </Card>
    </Stack>
  )
}

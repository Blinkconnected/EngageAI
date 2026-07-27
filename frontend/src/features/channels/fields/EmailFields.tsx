import { useState } from 'react'
import { Collapse, FormControlLabel, Stack, Switch, TextField, Typography } from '@mui/material'
import { useTranslation } from 'react-i18next'
import { fieldBool, fieldValue, type ChannelFieldsProps } from './types'

export function EmailFields({ credentials, onChange }: ChannelFieldsProps) {
  const { t } = useTranslation('channelsFields')
  const [imapExpanded, setImapExpanded] = useState(Boolean(fieldValue(credentials, 'imap_host')))

  return (
    <Stack spacing={2}>
      <Typography variant="subtitle2" color="text.secondary">
        {t('EmailFields.smtpSectionTitle')}
      </Typography>
      <TextField
        label={t('EmailFields.smtpHostLabel')}
        value={fieldValue(credentials, 'smtp_host')}
        onChange={(event) => onChange({ ...credentials, smtp_host: event.target.value })}
        required
        fullWidth
        placeholder={t('EmailFields.smtpHostPlaceholder')}
        helperText={t('EmailFields.smtpHostHelperText')}
      />
      <Stack direction="row" spacing={2}>
        <TextField
          label={t('EmailFields.smtpPortLabel')}
          value={fieldValue(credentials, 'smtp_port') || '587'}
          onChange={(event) => onChange({ ...credentials, smtp_port: event.target.value })}
          sx={{ width: 140 }}
        />
        <FormControlLabel
          control={
            <Switch
              checked={fieldBool(credentials, 'smtp_use_tls', true)}
              onChange={(event) => onChange({ ...credentials, smtp_use_tls: event.target.checked })}
            />
          }
          label={t('EmailFields.useTlsLabel')}
        />
      </Stack>
      <TextField
        label={t('EmailFields.smtpUsernameLabel')}
        value={fieldValue(credentials, 'smtp_username')}
        onChange={(event) => onChange({ ...credentials, smtp_username: event.target.value })}
        fullWidth
        placeholder={t('EmailFields.smtpUsernamePlaceholder')}
      />
      <TextField
        label={t('EmailFields.smtpPasswordLabel')}
        type="password"
        value={fieldValue(credentials, 'smtp_password')}
        onChange={(event) => onChange({ ...credentials, smtp_password: event.target.value })}
        helperText={t('EmailFields.smtpPasswordHelperText')}
        fullWidth
      />
      <TextField
        label={t('EmailFields.fromAddressLabel')}
        value={fieldValue(credentials, 'from_address')}
        onChange={(event) => onChange({ ...credentials, from_address: event.target.value })}
        fullWidth
        helperText={t('EmailFields.fromAddressHelperText')}
      />

      <FormControlLabel
        control={
          <Switch
            checked={imapExpanded}
            onChange={(event) => setImapExpanded(event.target.checked)}
          />
        }
        label={t('EmailFields.imapToggleLabel')}
      />
      <Collapse in={imapExpanded}>
        {/* Conditionally MOUNTED, not just visually collapsed — see the
            identical fix in ChannelEditDialog.tsx. MUI's Collapse only
            animates height; it doesn't unmount children, so a hidden
            `required` IMAP field (present or added later) would still
            block native HTML5 form validation on submit even while
            invisible. */}
        {imapExpanded && (
          <Stack spacing={2}>
            <Typography variant="subtitle2" color="text.secondary">
              {t('EmailFields.imapSectionTitle')}
            </Typography>
            <TextField
              label={t('EmailFields.imapHostLabel')}
              value={fieldValue(credentials, 'imap_host')}
              onChange={(event) => onChange({ ...credentials, imap_host: event.target.value })}
              fullWidth
              placeholder={t('EmailFields.imapHostPlaceholder')}
            />
            <Stack direction="row" spacing={2}>
              <TextField
                label={t('EmailFields.imapPortLabel')}
                value={fieldValue(credentials, 'imap_port') || '993'}
                onChange={(event) => onChange({ ...credentials, imap_port: event.target.value })}
                sx={{ width: 140 }}
              />
              <FormControlLabel
                control={
                  <Switch
                    checked={fieldBool(credentials, 'imap_use_ssl', true)}
                    onChange={(event) =>
                      onChange({ ...credentials, imap_use_ssl: event.target.checked })
                    }
                  />
                }
                label={t('EmailFields.useSslLabel')}
              />
            </Stack>
            <TextField
              label={t('EmailFields.imapUsernameLabel')}
              value={fieldValue(credentials, 'imap_username')}
              onChange={(event) => onChange({ ...credentials, imap_username: event.target.value })}
              fullWidth
            />
            <TextField
              label={t('EmailFields.imapPasswordLabel')}
              type="password"
              value={fieldValue(credentials, 'imap_password')}
              onChange={(event) => onChange({ ...credentials, imap_password: event.target.value })}
              fullWidth
            />
            <TextField
              label={t('EmailFields.imapFolderLabel')}
              value={fieldValue(credentials, 'imap_folder') || 'INBOX'}
              onChange={(event) => onChange({ ...credentials, imap_folder: event.target.value })}
              fullWidth
            />
          </Stack>
        )}
      </Collapse>
    </Stack>
  )
}

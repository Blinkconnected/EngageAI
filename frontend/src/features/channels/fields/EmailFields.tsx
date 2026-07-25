import { useState } from 'react'
import {
  Collapse,
  FormControlLabel,
  Stack,
  Switch,
  TextField,
  Typography,
} from '@mui/material'
import { fieldBool, fieldValue, type ChannelFieldsProps } from './types'

export function EmailFields({ credentials, onChange }: ChannelFieldsProps) {
  const [imapExpanded, setImapExpanded] = useState(Boolean(fieldValue(credentials, 'imap_host')))

  return (
    <Stack spacing={2}>
      <Typography variant="subtitle2" color="text.secondary">
        Outbound (SMTP)
      </Typography>
      <TextField
        label="SMTP host"
        value={fieldValue(credentials, 'smtp_host')}
        onChange={(event) => onChange({ ...credentials, smtp_host: event.target.value })}
        required
        fullWidth
      />
      <Stack direction="row" spacing={2}>
        <TextField
          label="SMTP port"
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
          label="Use TLS"
        />
      </Stack>
      <TextField
        label="SMTP username"
        value={fieldValue(credentials, 'smtp_username')}
        onChange={(event) => onChange({ ...credentials, smtp_username: event.target.value })}
        fullWidth
      />
      <TextField
        label="SMTP password"
        type="password"
        value={fieldValue(credentials, 'smtp_password')}
        onChange={(event) => onChange({ ...credentials, smtp_password: event.target.value })}
        fullWidth
      />
      <TextField
        label="From address"
        value={fieldValue(credentials, 'from_address')}
        onChange={(event) => onChange({ ...credentials, from_address: event.target.value })}
        fullWidth
        helperText="Defaults to the SMTP username if left blank"
      />

      <FormControlLabel
        control={
          <Switch checked={imapExpanded} onChange={(event) => setImapExpanded(event.target.checked)} />
        }
        label="Also receive replies (IMAP)"
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
              Inbound (IMAP)
            </Typography>
            <TextField
              label="IMAP host"
              value={fieldValue(credentials, 'imap_host')}
              onChange={(event) => onChange({ ...credentials, imap_host: event.target.value })}
              fullWidth
            />
            <Stack direction="row" spacing={2}>
              <TextField
                label="IMAP port"
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
                label="Use SSL"
              />
            </Stack>
            <TextField
              label="IMAP username"
              value={fieldValue(credentials, 'imap_username')}
              onChange={(event) => onChange({ ...credentials, imap_username: event.target.value })}
              fullWidth
            />
            <TextField
              label="IMAP password"
              type="password"
              value={fieldValue(credentials, 'imap_password')}
              onChange={(event) => onChange({ ...credentials, imap_password: event.target.value })}
              fullWidth
            />
            <TextField
              label="IMAP folder"
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

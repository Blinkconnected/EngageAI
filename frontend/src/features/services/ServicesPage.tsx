import { useState } from 'react'
import {
  Alert,
  Box,
  Button,
  Chip,
  Divider,
  FormControlLabel,
  MenuItem,
  Stack,
  Switch,
  TextField,
  Typography,
} from '@mui/material'
import AddIcon from '@mui/icons-material/Add'
import { useTranslation } from 'react-i18next'

import { PageHeader } from '../../shared/components/PageHeader'
import { EmptyState } from '../../shared/components/EmptyState'
import { LoadingState } from '../../shared/components/LoadingState'
import { ErrorState } from '../../shared/components/ErrorState'
import { ConfirmDialog } from '../../shared/components/ConfirmDialog'
import { usePermissions } from '../../shared/hooks/usePermissions'
import { useAllQueuesQuery } from '../queues/api'
import {
  useArchiveServiceMutation,
  useCreateServiceMutation,
  useServiceQuery,
  useServiceVersionsQuery,
  useServicesQuery,
  useUpdateServiceMutation,
} from './api'
import type { Service, ServiceUpdateRequest, ServiceVersion } from './types'

/** Blank means "not measured", which is different from 0 — that would mean
 * a target already breached the moment it starts. So an empty box maps to
 * null rather than to zero. */
function toMinutes(value: string): number | null {
  const trimmed = value.trim()
  if (trimmed === '') return null
  const parsed = Number(trimmed)
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : null
}

function minutesText(value: number | null | undefined): string {
  return value === null || value === undefined ? '' : String(value)
}

function ServiceEditor({
  service,
  canManage,
  onClose,
}: {
  service: Service
  canManage: boolean
  onClose: () => void
}) {
  const { t } = useTranslation('services')
  const queues = useAllQueuesQuery()
  const update = useUpdateServiceMutation()
  const versions = useServiceVersionsQuery(service.id)
  const detail = useServiceQuery(service.id)
  /** The configuration new conversations bind to. Fetched here rather than
   * passed in, so the editor always shows what is actually in force. */
  const version: ServiceVersion | null = detail.data?.current ?? null

  /** Edits held as an overlay on what was loaded, not copied in by an
   * effect — the same reasoning as the mail and payments screens. */
  const [edits, setEdits] = useState<ServiceUpdateRequest>({})
  const [note, setNote] = useState('')
  const [minted, setMinted] = useState<number | null>(null)

  const dirty = Object.keys(edits).length > 0

  const sla = {
    queue_minutes: version?.sla_queue_minutes ?? null,
    first_response_minutes: version?.sla_first_response_minutes ?? null,
    next_response_minutes: version?.sla_next_response_minutes ?? null,
    resolution_minutes: version?.sla_resolution_minutes ?? null,
    ...(edits.sla ?? {}),
  }

  const handleSave = () => {
    const changes: ServiceUpdateRequest = { ...edits }
    if (note.trim() !== '') changes.change_note = note.trim()
    update.mutate(
      { serviceId: service.id, changes },
      {
        onSuccess: (saved) => {
          setEdits({})
          setNote('')
          // Reported plainly. An administrator who cannot tell "saved" from
          // "version 4 created" cannot predict which of their edits reach
          // conversations already in progress.
          setMinted(saved.version_minted ? (saved.current?.version ?? null) : null)
          void versions.refetch()
        },
      },
    )
  }

  return (
    <Stack spacing={2}>
      <Stack direction="row" spacing={1} sx={{ alignItems: 'center', flexWrap: 'wrap' }}>
        <Typography variant="h6" sx={{ flexGrow: 1 }}>
          {service.name}
        </Typography>
        <Chip size="small" variant="outlined" label={service.code} />
        {version ? (
          <Chip size="small" label={t('editor.versionChip', { version: version.version })} />
        ) : null}
        {!service.is_active ? (
          <Chip size="small" color="warning" label={t('editor.inactive')} />
        ) : null}
      </Stack>

      {minted !== null ? (
        <Alert severity="success" onClose={() => setMinted(null)}>
          {t('editor.versionCreated', { version: minted })}
        </Alert>
      ) : null}
      {update.isError ? <Alert severity="error">{t('editor.saveFailed')}</Alert> : null}

      <TextField
        label={t('field.name')}
        value={edits.name ?? service.name}
        onChange={(e) => setEdits((c) => ({ ...c, name: e.target.value }))}
        disabled={!canManage}
        size="small"
        fullWidth
      />
      <TextField
        label={t('field.description')}
        value={edits.description ?? service.description ?? ''}
        onChange={(e) => setEdits((c) => ({ ...c, description: e.target.value }))}
        disabled={!canManage}
        size="small"
        fullWidth
      />
      <TextField
        select
        label={t('field.queue')}
        value={edits.logical_queue_id ?? version?.logical_queue_id ?? ''}
        onChange={(e) => setEdits((c) => ({ ...c, logical_queue_id: e.target.value || null }))}
        disabled={!canManage}
        helperText={t('field.queueHelp')}
        size="small"
        fullWidth
      >
        <MenuItem value="">{t('field.noQueue')}</MenuItem>
        {(queues.data ?? []).map((queue) => (
          <MenuItem key={queue.id} value={queue.id}>
            {queue.name}
          </MenuItem>
        ))}
      </TextField>

      <Divider textAlign="left">
        <Typography variant="overline">{t('editor.slaHeading')}</Typography>
      </Divider>
      <Typography variant="caption" color="text.secondary">
        {t('editor.slaHelp')}
      </Typography>
      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
        {(
          [
            ['queue_minutes', t('field.slaQueue')],
            ['first_response_minutes', t('field.slaFirstResponse')],
            ['next_response_minutes', t('field.slaNextResponse')],
            ['resolution_minutes', t('field.slaResolution')],
          ] as const
        ).map(([key, label]) => (
          <TextField
            key={key}
            label={label}
            value={minutesText(sla[key])}
            onChange={(e) =>
              setEdits((c) => ({
                ...c,
                sla: { ...sla, [key]: toMinutes(e.target.value) },
              }))
            }
            disabled={!canManage}
            placeholder={t('field.notMeasured')}
            size="small"
            fullWidth
          />
        ))}
      </Stack>

      <Divider textAlign="left">
        <Typography variant="overline">{t('editor.aiHeading')}</Typography>
      </Divider>
      <FormControlLabel
        control={
          <Switch
            checked={edits.ai?.enabled ?? version?.ai_enabled ?? false}
            onChange={(e) =>
              setEdits((c) => ({
                ...c,
                ai: {
                  enabled: e.target.checked,
                  pickup_delay_seconds:
                    c.ai?.pickup_delay_seconds ?? version?.ai_pickup_delay_seconds ?? 30,
                  resume_delay_seconds:
                    c.ai?.resume_delay_seconds ?? version?.ai_resume_delay_seconds ?? 900,
                  confidence_threshold:
                    c.ai?.confidence_threshold ?? version?.ai_confidence_threshold ?? '0.75',
                },
              }))
            }
            disabled={!canManage}
          />
        }
        label={t('field.aiEnabled')}
      />

      <Divider />
      <TextField
        label={t('field.changeNote')}
        value={note}
        onChange={(e) => setNote(e.target.value)}
        disabled={!canManage}
        helperText={t('field.changeNoteHelp')}
        size="small"
        fullWidth
      />

      <Stack direction="row" spacing={1}>
        <Button onClick={onClose}>{t('action.close')}</Button>
        <Box sx={{ flexGrow: 1 }} />
        <Button
          variant="contained"
          onClick={handleSave}
          disabled={!canManage || !dirty || update.isPending}
        >
          {t('action.save')}
        </Button>
      </Stack>

      {(versions.data ?? []).length > 1 ? (
        <>
          <Divider textAlign="left">
            <Typography variant="overline">{t('editor.historyHeading')}</Typography>
          </Divider>
          <Typography variant="caption" color="text.secondary">
            {t('editor.historyHelp')}
          </Typography>
          <Stack spacing={0.5}>
            {(versions.data ?? []).map((entry) => (
              <Typography key={entry.id} variant="body2" color="text.secondary">
                {t('editor.historyLine', {
                  version: entry.version,
                  note: entry.change_note ?? t('editor.noNote'),
                })}
              </Typography>
            ))}
          </Stack>
        </>
      ) : null}
    </Stack>
  )
}

export function ServicesPage() {
  const { t } = useTranslation('services')
  const { hasPermission } = usePermissions()
  const canManage = hasPermission('queues.manage')

  const services = useServicesQuery()
  const create = useCreateServiceMutation()
  const archive = useArchiveServiceMutation()

  const [selected, setSelected] = useState<Service | null>(null)
  const [archiving, setArchiving] = useState<Service | null>(null)
  const [newName, setNewName] = useState('')

  if (services.isLoading) return <LoadingState />
  if (services.isError)
    return <ErrorState error={services.error} onRetry={() => void services.refetch()} />

  const items = services.data ?? []

  const handleCreate = () => {
    const name = newName.trim()
    if (name === '') return
    create.mutate(
      {
        name,
        // Derived from the name, lowercased and punctuation-stripped, so an
        // operator is not asked for two things when they are thinking of one.
        code: name
          .toLowerCase()
          .replace(/[^a-z0-9]+/g, '-')
          .replace(/^-|-$/g, '')
          .slice(0, 64),
        display_order: items.length + 1,
      },
      {
        onSuccess: (saved) => {
          setNewName('')
          setSelected(saved.service)
        },
      },
    )
  }

  return (
    <Stack spacing={3}>
      <PageHeader title={t('title')} description={t('subtitle')} />

      {canManage ? (
        <Stack direction="row" spacing={1} sx={{ alignItems: 'flex-start' }}>
          <TextField
            label={t('create.name')}
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            size="small"
            sx={{ maxWidth: 320 }}
          />
          <Button
            variant="contained"
            startIcon={<AddIcon />}
            onClick={handleCreate}
            disabled={newName.trim() === '' || create.isPending}
          >
            {t('create.submit')}
          </Button>
        </Stack>
      ) : null}
      {create.isError ? <Alert severity="error">{t('create.failed')}</Alert> : null}

      {items.length === 0 ? (
        <EmptyState title={t('empty.title')} description={t('empty.description')} />
      ) : (
        <Stack
          direction={{ xs: 'column', md: 'row' }}
          spacing={3}
          sx={{ alignItems: 'flex-start' }}
        >
          <Stack spacing={1} sx={{ minWidth: 240 }}>
            {items.map((item) => (
              <Button
                key={item.id}
                variant={selected?.id === item.id ? 'contained' : 'outlined'}
                onClick={() => setSelected(item)}
                sx={{ justifyContent: 'flex-start' }}
              >
                {item.name}
              </Button>
            ))}
          </Stack>

          <Box sx={{ flexGrow: 1, width: '100%' }}>
            {selected ? (
              <Stack spacing={2}>
                <ServiceEditor
                  key={selected.id}
                  service={items.find((s) => s.id === selected.id) ?? selected}
                  canManage={canManage}
                  onClose={() => setSelected(null)}
                />
                {canManage ? (
                  <Button color="error" onClick={() => setArchiving(selected)}>
                    {t('action.archive')}
                  </Button>
                ) : null}
              </Stack>
            ) : (
              <Typography variant="body2" color="text.secondary">
                {t('selectPrompt')}
              </Typography>
            )}
          </Box>
        </Stack>
      )}

      <ConfirmDialog
        open={archiving !== null}
        title={t('archive.title')}
        // Said plainly: archiving removes it from the directory and leaves
        // every conversation that ran in it able to say so.
        description={t('archive.description')}
        confirmLabel={t('action.archive')}
        onConfirm={() => {
          if (archiving) {
            archive.mutate(archiving.id, {
              onSuccess: () => {
                if (selected?.id === archiving.id) setSelected(null)
              },
            })
          }
          setArchiving(null)
        }}
        onClose={() => setArchiving(null)}
      />
    </Stack>
  )
}

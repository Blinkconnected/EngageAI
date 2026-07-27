import { useState } from 'react'
import {
  Alert,
  Box,
  Button,
  Chip,
  IconButton,
  MenuItem,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Tab,
  Tabs,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material'
import AddIcon from '@mui/icons-material/Add'
import EditOutlinedIcon from '@mui/icons-material/EditOutlined'
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutlined'
import { PageHeader } from '../../shared/components/PageHeader'
import { ConfirmDialog } from '../../shared/components/ConfirmDialog'
import { LoadingState } from '../../shared/components/LoadingState'
import { ErrorState } from '../../shared/components/ErrorState'
import { EmptyState } from '../../shared/components/EmptyState'
import { extractErrorMessage } from '../../shared/api/errors'
import { usePermissions } from '../../shared/hooks/usePermissions'
import { HolidayCreateDialog } from './HolidayCreateDialog'
import { SlaPolicyCreateDialog } from './SlaPolicyCreateDialog'
import { SlaPolicyEditDialog } from './SlaPolicyEditDialog'
import {
  useDeleteHolidayMutation,
  useDeleteSlaPolicyMutation,
  useHolidaysQuery,
  usePreviewSlaPolicyMutation,
  useSlaPoliciesQuery,
} from './api'
import type { SlaPolicy } from './types'

function targetLabel(minutes: number | null): string {
  return minutes ? `${minutes} min` : '—'
}

function PoliciesTab({ canManage }: { canManage: boolean }) {
  const policiesQuery = useSlaPoliciesQuery()
  const deleteMutation = useDeleteSlaPolicyMutation()

  const [createOpen, setCreateOpen] = useState(false)
  const [editingPolicy, setEditingPolicy] = useState<SlaPolicy | null>(null)
  const [deletingPolicy, setDeletingPolicy] = useState<SlaPolicy | null>(null)

  return (
    <>
      {canManage && (
        <Box sx={{ display: 'flex', justifyContent: 'flex-end', mb: 2 }}>
          <Button variant="contained" startIcon={<AddIcon />} onClick={() => setCreateOpen(true)}>
            New policy
          </Button>
        </Box>
      )}

      {policiesQuery.isPending && <LoadingState label="Loading SLA policies…" />}
      {policiesQuery.isError && (
        <ErrorState error={policiesQuery.error} onRetry={() => policiesQuery.refetch()} />
      )}
      {policiesQuery.data && policiesQuery.data.length === 0 && (
        <EmptyState
          title="No SLA policies yet"
          description="Create a policy to set response/resolution targets, business hours awareness, and escalation rules — then assign it to a queue."
          action={
            canManage && (
              <Button variant="contained" onClick={() => setCreateOpen(true)}>
                New policy
              </Button>
            )
          }
        />
      )}
      {policiesQuery.data && policiesQuery.data.length > 0 && (
        <TableContainer>
          <Table aria-label="SLA policies">
            <TableHead>
              <TableRow>
                <TableCell>Name</TableCell>
                <TableCell>First response</TableCell>
                <TableCell>Resolution</TableCell>
                <TableCell>Warning</TableCell>
                <TableCell>Business hours</TableCell>
                <TableCell>Status</TableCell>
                <TableCell align="right">Queues</TableCell>
                {canManage && <TableCell align="right">Actions</TableCell>}
              </TableRow>
            </TableHead>
            <TableBody>
              {policiesQuery.data.map((policy) => {
                const blockedReason =
                  policy.assigned_queue_count > 0
                    ? `Reassign ${policy.assigned_queue_count === 1 ? 'the queue' : 'all queues'} using this policy before deleting it.`
                    : null
                return (
                  <TableRow key={policy.id}>
                    <TableCell>{policy.name}</TableCell>
                    <TableCell>{targetLabel(policy.first_response_target_minutes)}</TableCell>
                    <TableCell>{targetLabel(policy.resolution_target_minutes)}</TableCell>
                    <TableCell>{policy.warning_threshold_percent}%</TableCell>
                    <TableCell>{policy.business_hours_aware ? 'Yes' : 'No'}</TableCell>
                    <TableCell>
                      <Chip
                        label={policy.is_active ? 'Active' : 'Inactive'}
                        size="small"
                        color={policy.is_active ? 'success' : 'default'}
                      />
                    </TableCell>
                    <TableCell align="right">{policy.assigned_queue_count}</TableCell>
                    {canManage && (
                      <TableCell align="right">
                        <Stack direction="row" spacing={0.5} sx={{ justifyContent: 'flex-end' }}>
                          <Tooltip title="Edit">
                            <IconButton
                              size="small"
                              onClick={() => setEditingPolicy(policy)}
                              aria-label={`Edit ${policy.name}`}
                            >
                              <EditOutlinedIcon fontSize="small" />
                            </IconButton>
                          </Tooltip>
                          <Tooltip title={blockedReason ?? 'Delete'}>
                            <span>
                              <IconButton
                                size="small"
                                disabled={blockedReason !== null}
                                onClick={() => setDeletingPolicy(policy)}
                                aria-label={`Delete ${policy.name}`}
                              >
                                <DeleteOutlineIcon fontSize="small" />
                              </IconButton>
                            </span>
                          </Tooltip>
                        </Stack>
                      </TableCell>
                    )}
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        </TableContainer>
      )}

      {canManage && (
        <>
          <SlaPolicyCreateDialog open={createOpen} onClose={() => setCreateOpen(false)} />
          <SlaPolicyEditDialog policy={editingPolicy} onClose={() => setEditingPolicy(null)} />
          <ConfirmDialog
            open={Boolean(deletingPolicy)}
            title="Remove SLA policy"
            description={`Remove ${deletingPolicy?.name ?? ''}? This cannot be undone.`}
            confirmLabel="Remove"
            confirmColor="error"
            isConfirming={deleteMutation.isPending}
            onConfirm={() => {
              if (deletingPolicy) {
                deleteMutation.mutate(deletingPolicy.id, {
                  onSuccess: () => setDeletingPolicy(null),
                })
              }
            }}
            onClose={() => setDeletingPolicy(null)}
          />
        </>
      )}
    </>
  )
}

function HolidaysTab({ canManage }: { canManage: boolean }) {
  const holidaysQuery = useHolidaysQuery()
  const deleteMutation = useDeleteHolidayMutation()
  const [createOpen, setCreateOpen] = useState(false)

  return (
    <>
      {canManage && (
        <Box sx={{ display: 'flex', justifyContent: 'flex-end', mb: 2 }}>
          <Button variant="contained" startIcon={<AddIcon />} onClick={() => setCreateOpen(true)}>
            New holiday
          </Button>
        </Box>
      )}

      {holidaysQuery.isPending && <LoadingState label="Loading holidays…" />}
      {holidaysQuery.isError && (
        <ErrorState error={holidaysQuery.error} onRetry={() => holidaysQuery.refetch()} />
      )}
      {holidaysQuery.data && holidaysQuery.data.length === 0 && (
        <EmptyState
          title="No holidays yet"
          description="Add a holiday to exclude it from business-hours-aware SLA deadlines."
          action={
            canManage && (
              <Button variant="contained" onClick={() => setCreateOpen(true)}>
                New holiday
              </Button>
            )
          }
        />
      )}
      {holidaysQuery.data && holidaysQuery.data.length > 0 && (
        <TableContainer>
          <Table aria-label="Holidays">
            <TableHead>
              <TableRow>
                <TableCell>Name</TableCell>
                <TableCell>Date</TableCell>
                <TableCell>Repeats yearly</TableCell>
                {canManage && <TableCell align="right">Actions</TableCell>}
              </TableRow>
            </TableHead>
            <TableBody>
              {holidaysQuery.data.map((holiday) => (
                <TableRow key={holiday.id}>
                  <TableCell>{holiday.name}</TableCell>
                  <TableCell>{holiday.date}</TableCell>
                  <TableCell>{holiday.recurs_annually ? 'Yes' : 'No'}</TableCell>
                  {canManage && (
                    <TableCell align="right">
                      <Tooltip title="Delete">
                        <IconButton
                          size="small"
                          onClick={() => deleteMutation.mutate(holiday.id)}
                          aria-label={`Delete ${holiday.name}`}
                        >
                          <DeleteOutlineIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                    </TableCell>
                  )}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}

      {canManage && (
        <HolidayCreateDialog open={createOpen} onClose={() => setCreateOpen(false)} />
      )}
    </>
  )
}

function formatDeadline(value: string | null): string {
  if (!value) return 'No target set'
  return new Date(value).toLocaleString()
}

function PreviewTab() {
  const policiesQuery = useSlaPoliciesQuery()
  const previewMutation = usePreviewSlaPolicyMutation()
  const [policyId, setPolicyId] = useState('')
  const [startsAt, setStartsAt] = useState('')

  function handlePreview() {
    if (!policyId || !startsAt) return
    previewMutation.mutate({ policy_id: policyId, starts_at: new Date(startsAt).toISOString() })
  }

  return (
    <Stack spacing={2} sx={{ maxWidth: 480 }}>
      <Typography variant="body2" color="text.secondary">
        See exactly when a policy's warnings and deadlines would land for a hypothetical
        conversation — no real data is touched.
      </Typography>
      <TextField
        select
        label="Policy"
        value={policyId}
        disabled={policiesQuery.isPending}
        onChange={(event) => setPolicyId(event.target.value)}
        fullWidth
      >
        {policiesQuery.data?.map((policy) => (
          <MenuItem key={policy.id} value={policy.id}>
            {policy.name}
          </MenuItem>
        ))}
      </TextField>
      <TextField
        label="Conversation created at"
        type="datetime-local"
        value={startsAt}
        onChange={(event) => setStartsAt(event.target.value)}
        fullWidth
        slotProps={{ inputLabel: { shrink: true } }}
      />
      <Button
        variant="contained"
        onClick={handlePreview}
        disabled={!policyId || !startsAt || previewMutation.isPending}
        sx={{ alignSelf: 'flex-start' }}
      >
        {previewMutation.isPending ? 'Calculating…' : 'Preview'}
      </Button>

      {previewMutation.isError && (
        <Alert severity="error">{extractErrorMessage(previewMutation.error)}</Alert>
      )}
      {previewMutation.isSuccess && (
        <TableContainer>
          <Table size="small" aria-label="SLA preview">
            <TableBody>
              <TableRow>
                <TableCell>First response warning</TableCell>
                <TableCell>{formatDeadline(previewMutation.data.first_response_warning_at)}</TableCell>
              </TableRow>
              <TableRow>
                <TableCell>First response deadline</TableCell>
                <TableCell>{formatDeadline(previewMutation.data.first_response_deadline)}</TableCell>
              </TableRow>
              <TableRow>
                <TableCell>Resolution warning</TableCell>
                <TableCell>{formatDeadline(previewMutation.data.resolution_warning_at)}</TableCell>
              </TableRow>
              <TableRow>
                <TableCell>Resolution deadline</TableCell>
                <TableCell>{formatDeadline(previewMutation.data.resolution_deadline)}</TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </TableContainer>
      )}
    </Stack>
  )
}

export function SlaBuilderPage() {
  const { hasPermission } = usePermissions()
  const canManage = hasPermission('sla_policies.manage')
  const [tab, setTab] = useState<'policies' | 'holidays' | 'preview'>('policies')

  return (
    <>
      <PageHeader
        title="SLA Builder"
        description="Define response and resolution targets, business hours and holidays, warning thresholds, and automatic escalation."
      />

      <Tabs value={tab} onChange={(_event, value) => setTab(value)} sx={{ mb: 2 }}>
        <Tab label="Policies" value="policies" />
        <Tab label="Holidays" value="holidays" />
        <Tab label="Preview" value="preview" />
      </Tabs>

      {tab === 'policies' && <PoliciesTab canManage={canManage} />}
      {tab === 'holidays' && <HolidaysTab canManage={canManage} />}
      {tab === 'preview' && <PreviewTab />}
    </>
  )
}

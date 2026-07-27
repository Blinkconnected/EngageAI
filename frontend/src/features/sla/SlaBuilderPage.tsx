import { useState } from 'react'
import {
  Alert,
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
import { useTranslation } from 'react-i18next'
import type { TFunction } from 'i18next'
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

function targetLabel(minutes: number | null, t: TFunction<'sla'>): string {
  return minutes
    ? t('SlaBuilderPage.targetMinutesLabel', { minutes })
    : t('SlaBuilderPage.noTargetDash')
}

function PoliciesTab({
  canManage,
  createOpen,
  onOpenCreate,
  onCloseCreate,
}: {
  canManage: boolean
  createOpen: boolean
  onOpenCreate: () => void
  onCloseCreate: () => void
}) {
  const { t } = useTranslation('sla')
  const policiesQuery = useSlaPoliciesQuery()
  const deleteMutation = useDeleteSlaPolicyMutation()

  const [editingPolicy, setEditingPolicy] = useState<SlaPolicy | null>(null)
  const [deletingPolicy, setDeletingPolicy] = useState<SlaPolicy | null>(null)

  return (
    <>
      {policiesQuery.isPending && (
        <LoadingState label={t('SlaBuilderPage.policiesTab.loadingLabel')} />
      )}
      {policiesQuery.isError && (
        <ErrorState error={policiesQuery.error} onRetry={() => policiesQuery.refetch()} />
      )}
      {policiesQuery.data && policiesQuery.data.length === 0 && (
        <EmptyState
          title={t('SlaBuilderPage.policiesTab.emptyTitle')}
          description={t('SlaBuilderPage.policiesTab.emptyDescription')}
          action={
            canManage && (
              <Button variant="contained" onClick={onOpenCreate}>
                {t('SlaBuilderPage.newPolicyButton')}
              </Button>
            )
          }
        />
      )}
      {policiesQuery.data && policiesQuery.data.length > 0 && (
        <TableContainer>
          <Table aria-label={t('SlaBuilderPage.policiesTab.tableAriaLabel')}>
            <TableHead>
              <TableRow>
                <TableCell>{t('SlaBuilderPage.policiesTab.nameColumn')}</TableCell>
                <TableCell>{t('SlaBuilderPage.policiesTab.firstResponseColumn')}</TableCell>
                <TableCell>{t('SlaBuilderPage.policiesTab.resolutionColumn')}</TableCell>
                <TableCell>{t('SlaBuilderPage.policiesTab.warningColumn')}</TableCell>
                <TableCell>{t('SlaBuilderPage.policiesTab.businessHoursColumn')}</TableCell>
                <TableCell>{t('SlaBuilderPage.policiesTab.statusColumn')}</TableCell>
                <TableCell align="right">{t('SlaBuilderPage.policiesTab.queuesColumn')}</TableCell>
                {canManage && (
                  <TableCell align="right">
                    {t('SlaBuilderPage.policiesTab.actionsColumn')}
                  </TableCell>
                )}
              </TableRow>
            </TableHead>
            <TableBody>
              {policiesQuery.data.map((policy) => {
                const blockedReason =
                  policy.assigned_queue_count > 0
                    ? policy.assigned_queue_count === 1
                      ? t('SlaBuilderPage.policiesTab.blockedReasonSingular')
                      : t('SlaBuilderPage.policiesTab.blockedReasonPlural')
                    : null
                return (
                  <TableRow key={policy.id}>
                    <TableCell>{policy.name}</TableCell>
                    <TableCell>{targetLabel(policy.first_response_target_minutes, t)}</TableCell>
                    <TableCell>{targetLabel(policy.resolution_target_minutes, t)}</TableCell>
                    <TableCell>{policy.warning_threshold_percent}%</TableCell>
                    <TableCell>
                      {policy.business_hours_aware
                        ? t('SlaBuilderPage.yesLabel')
                        : t('SlaBuilderPage.noLabel')}
                    </TableCell>
                    <TableCell>
                      <Chip
                        label={
                          policy.is_active
                            ? t('SlaBuilderPage.policiesTab.activeChipLabel')
                            : t('SlaBuilderPage.policiesTab.inactiveChipLabel')
                        }
                        size="small"
                        color={policy.is_active ? 'success' : 'default'}
                      />
                    </TableCell>
                    <TableCell align="right">{policy.assigned_queue_count}</TableCell>
                    {canManage && (
                      <TableCell align="right">
                        <Stack direction="row" spacing={0.5} sx={{ justifyContent: 'flex-end' }}>
                          <Tooltip title={t('SlaBuilderPage.policiesTab.editTooltip')}>
                            <IconButton
                              size="small"
                              onClick={() => setEditingPolicy(policy)}
                              aria-label={t('SlaBuilderPage.policiesTab.editAriaLabel', {
                                name: policy.name,
                              })}
                            >
                              <EditOutlinedIcon fontSize="small" />
                            </IconButton>
                          </Tooltip>
                          <Tooltip
                            title={blockedReason ?? t('SlaBuilderPage.policiesTab.deleteTooltip')}
                          >
                            <span>
                              <IconButton
                                size="small"
                                disabled={blockedReason !== null}
                                onClick={() => setDeletingPolicy(policy)}
                                aria-label={t('SlaBuilderPage.policiesTab.deleteAriaLabel', {
                                  name: policy.name,
                                })}
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
          <SlaPolicyCreateDialog open={createOpen} onClose={onCloseCreate} />
          <SlaPolicyEditDialog policy={editingPolicy} onClose={() => setEditingPolicy(null)} />
          <ConfirmDialog
            open={Boolean(deletingPolicy)}
            title={t('SlaBuilderPage.policiesTab.removeDialogTitle')}
            description={t('SlaBuilderPage.policiesTab.removeDialogDescription', {
              name: deletingPolicy?.name ?? '',
            })}
            confirmLabel={t('SlaBuilderPage.policiesTab.removeConfirmLabel')}
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

function HolidaysTab({
  canManage,
  createOpen,
  onOpenCreate,
  onCloseCreate,
}: {
  canManage: boolean
  createOpen: boolean
  onOpenCreate: () => void
  onCloseCreate: () => void
}) {
  const { t } = useTranslation('sla')
  const holidaysQuery = useHolidaysQuery()
  const deleteMutation = useDeleteHolidayMutation()

  return (
    <>
      {holidaysQuery.isPending && (
        <LoadingState label={t('SlaBuilderPage.holidaysTab.loadingLabel')} />
      )}
      {holidaysQuery.isError && (
        <ErrorState error={holidaysQuery.error} onRetry={() => holidaysQuery.refetch()} />
      )}
      {holidaysQuery.data && holidaysQuery.data.length === 0 && (
        <EmptyState
          title={t('SlaBuilderPage.holidaysTab.emptyTitle')}
          description={t('SlaBuilderPage.holidaysTab.emptyDescription')}
          action={
            canManage && (
              <Button variant="contained" onClick={onOpenCreate}>
                {t('SlaBuilderPage.newHolidayButton')}
              </Button>
            )
          }
        />
      )}
      {holidaysQuery.data && holidaysQuery.data.length > 0 && (
        <TableContainer>
          <Table aria-label={t('SlaBuilderPage.holidaysTab.tableAriaLabel')}>
            <TableHead>
              <TableRow>
                <TableCell>{t('SlaBuilderPage.holidaysTab.nameColumn')}</TableCell>
                <TableCell>{t('SlaBuilderPage.holidaysTab.dateColumn')}</TableCell>
                <TableCell>{t('SlaBuilderPage.holidaysTab.repeatsYearlyColumn')}</TableCell>
                {canManage && (
                  <TableCell align="right">
                    {t('SlaBuilderPage.holidaysTab.actionsColumn')}
                  </TableCell>
                )}
              </TableRow>
            </TableHead>
            <TableBody>
              {holidaysQuery.data.map((holiday) => (
                <TableRow key={holiday.id}>
                  <TableCell>{holiday.name}</TableCell>
                  <TableCell>{holiday.date}</TableCell>
                  <TableCell>
                    {holiday.recurs_annually
                      ? t('SlaBuilderPage.yesLabel')
                      : t('SlaBuilderPage.noLabel')}
                  </TableCell>
                  {canManage && (
                    <TableCell align="right">
                      <Tooltip title={t('SlaBuilderPage.holidaysTab.deleteTooltip')}>
                        <IconButton
                          size="small"
                          onClick={() => deleteMutation.mutate(holiday.id)}
                          aria-label={t('SlaBuilderPage.holidaysTab.deleteAriaLabel', {
                            name: holiday.name,
                          })}
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

      {canManage && <HolidayCreateDialog open={createOpen} onClose={onCloseCreate} />}
    </>
  )
}

function formatDeadline(value: string | null, t: TFunction<'sla'>): string {
  if (!value) return t('SlaBuilderPage.previewTab.noTargetSet')
  return new Date(value).toLocaleString()
}

function PreviewTab() {
  const { t } = useTranslation('sla')
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
        {t('SlaBuilderPage.previewTab.description')}
      </Typography>
      <TextField
        select
        label={t('SlaBuilderPage.previewTab.policyLabel')}
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
        label={t('SlaBuilderPage.previewTab.conversationCreatedAtLabel')}
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
        {previewMutation.isPending
          ? t('SlaBuilderPage.previewTab.calculatingButton')
          : t('SlaBuilderPage.previewTab.previewButton')}
      </Button>

      {previewMutation.isError && (
        <Alert severity="error">{extractErrorMessage(previewMutation.error)}</Alert>
      )}
      {previewMutation.isSuccess && (
        <TableContainer>
          <Table size="small" aria-label={t('SlaBuilderPage.previewTab.tableAriaLabel')}>
            <TableBody>
              <TableRow>
                <TableCell>{t('SlaBuilderPage.previewTab.firstResponseWarningRow')}</TableCell>
                <TableCell>
                  {formatDeadline(previewMutation.data.first_response_warning_at, t)}
                </TableCell>
              </TableRow>
              <TableRow>
                <TableCell>{t('SlaBuilderPage.previewTab.firstResponseDeadlineRow')}</TableCell>
                <TableCell>
                  {formatDeadline(previewMutation.data.first_response_deadline, t)}
                </TableCell>
              </TableRow>
              <TableRow>
                <TableCell>{t('SlaBuilderPage.previewTab.resolutionWarningRow')}</TableCell>
                <TableCell>
                  {formatDeadline(previewMutation.data.resolution_warning_at, t)}
                </TableCell>
              </TableRow>
              <TableRow>
                <TableCell>{t('SlaBuilderPage.previewTab.resolutionDeadlineRow')}</TableCell>
                <TableCell>{formatDeadline(previewMutation.data.resolution_deadline, t)}</TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </TableContainer>
      )}
    </Stack>
  )
}

export function SlaBuilderPage() {
  const { t } = useTranslation('sla')
  const { hasPermission } = usePermissions()
  const canManage = hasPermission('sla_policies.manage')
  const [tab, setTab] = useState<'policies' | 'holidays' | 'preview'>('policies')
  // Owned here, not per-tab, so the "+ New" action stays in the shared
  // PageHeader — stable top-right, and simply absent on the Preview tab
  // (which has no create action) — instead of moving/disappearing.
  const [policyCreateOpen, setPolicyCreateOpen] = useState(false)
  const [holidayCreateOpen, setHolidayCreateOpen] = useState(false)

  const headerAction =
    canManage &&
    (tab === 'policies' ? (
      <Button variant="contained" startIcon={<AddIcon />} onClick={() => setPolicyCreateOpen(true)}>
        {t('SlaBuilderPage.newPolicyButton')}
      </Button>
    ) : tab === 'holidays' ? (
      <Button
        variant="contained"
        startIcon={<AddIcon />}
        onClick={() => setHolidayCreateOpen(true)}
      >
        {t('SlaBuilderPage.newHolidayButton')}
      </Button>
    ) : null)

  return (
    <>
      <PageHeader
        title={t('SlaBuilderPage.pageTitle')}
        description={t('SlaBuilderPage.pageDescription')}
        actions={headerAction}
      />

      <Tabs value={tab} onChange={(_event, value) => setTab(value)} sx={{ mb: 2 }}>
        <Tab label={t('SlaBuilderPage.tabPolicies')} value="policies" />
        <Tab label={t('SlaBuilderPage.tabHolidays')} value="holidays" />
        <Tab label={t('SlaBuilderPage.tabPreview')} value="preview" />
      </Tabs>

      {tab === 'policies' && (
        <PoliciesTab
          canManage={canManage}
          createOpen={policyCreateOpen}
          onOpenCreate={() => setPolicyCreateOpen(true)}
          onCloseCreate={() => setPolicyCreateOpen(false)}
        />
      )}
      {tab === 'holidays' && (
        <HolidaysTab
          canManage={canManage}
          createOpen={holidayCreateOpen}
          onOpenCreate={() => setHolidayCreateOpen(true)}
          onCloseCreate={() => setHolidayCreateOpen(false)}
        />
      )}
      {tab === 'preview' && <PreviewTab />}
    </>
  )
}

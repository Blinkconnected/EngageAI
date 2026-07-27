import { useMemo, useState } from 'react'
import {
  Button,
  Chip,
  IconButton,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Tab,
  Tabs,
  Tooltip,
  Typography,
} from '@mui/material'
import AddIcon from '@mui/icons-material/Add'
import EditOutlinedIcon from '@mui/icons-material/EditOutlined'
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutlined'
import { GridActionsCellItem, type GridColDef } from '@mui/x-data-grid'
import { PageHeader } from '../../shared/components/PageHeader'
import { DataTable } from '../../shared/components/DataTable'
import { ConfirmDialog } from '../../shared/components/ConfirmDialog'
import { EmptyState } from '../../shared/components/EmptyState'
import { LoadingState } from '../../shared/components/LoadingState'
import { ErrorState } from '../../shared/components/ErrorState'
import { usePaginationParams } from '../../shared/api/pagination'
import { usePermissions } from '../../shared/hooks/usePermissions'
import { channelTypeLabel } from '../channels/types'
import { QueueCreateDialog } from './QueueCreateDialog'
import { QueueEditDialog } from './QueueEditDialog'
import { RoutingRuleCreateDialog } from './RoutingRuleCreateDialog'
import { RoutingRuleEditDialog } from './RoutingRuleEditDialog'
import {
  useAllQueuesQuery,
  useDeleteQueueMutation,
  useDeleteRoutingRuleMutation,
  useQueuesQuery,
  useRoutingRulesQuery,
} from './api'
import { QUEUE_ASSIGNMENT_STRATEGIES, type Queue, type RoutingRule } from './types'

function assignmentStrategyLabel(strategy: Queue['assignment_strategy']): string {
  return QUEUE_ASSIGNMENT_STRATEGIES.find((s) => s.value === strategy)?.label ?? strategy
}

function QueuesTab({
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
  const { page, pageSize, setPage, setPageSize, apiParams } = usePaginationParams()
  const queuesQuery = useQueuesQuery(apiParams)
  const routingRulesQuery = useRoutingRulesQuery()
  const deleteMutation = useDeleteQueueMutation()

  const [editingQueue, setEditingQueue] = useState<Queue | null>(null)
  const [deletingQueue, setDeletingQueue] = useState<Queue | null>(null)

  // How many routing rules still target each queue — deleting a queue
  // they depend on would leave those rules pointing nowhere, silently
  // failing to route any conversation matching them (the same class of
  // gap the SLA Builder's own Policies tab already guards against for
  // SLA policies assigned to queues).
  const ruleCountByQueue = useMemo(() => {
    const counts = new Map<string, number>()
    routingRulesQuery.data?.forEach((rule) => {
      counts.set(rule.target_queue_id, (counts.get(rule.target_queue_id) ?? 0) + 1)
    })
    return counts
  }, [routingRulesQuery.data])

  const columns: GridColDef<Queue>[] = useMemo(
    () => [
      { field: 'name', headerName: 'Name', flex: 1, minWidth: 160 },
      {
        field: 'assignment_strategy',
        headerName: 'Assignment',
        width: 150,
        valueGetter: (_value, row) => assignmentStrategyLabel(row.assignment_strategy),
      },
      {
        field: 'first_response_target_minutes',
        headerName: 'First response SLA',
        width: 150,
        valueGetter: (_value, row) =>
          row.first_response_target_minutes ? `${row.first_response_target_minutes} min` : '—',
      },
      {
        field: 'resolution_target_minutes',
        headerName: 'Resolution SLA',
        width: 140,
        valueGetter: (_value, row) =>
          row.resolution_target_minutes ? `${row.resolution_target_minutes} min` : '—',
      },
      {
        field: 'is_active',
        headerName: 'Status',
        width: 110,
        renderCell: (params) => (
          <Chip
            label={params.value ? 'Active' : 'Inactive'}
            size="small"
            color={params.value ? 'success' : 'default'}
          />
        ),
      },
      ...(canManage
        ? [
            {
              field: 'actions',
              type: 'actions' as const,
              headerName: 'Actions',
              width: 80,
              getActions: (params: { row: Queue }) => {
                const ruleCount = ruleCountByQueue.get(params.row.id) ?? 0
                const blockedReason =
                  ruleCount > 0
                    ? `${ruleCount} routing rule(s) still target this queue — repoint them before deleting it.`
                    : null
                return [
                  <GridActionsCellItem
                    key="edit"
                    icon={<EditOutlinedIcon fontSize="small" />}
                    label="Edit"
                    onClick={() => setEditingQueue(params.row)}
                  />,
                  <GridActionsCellItem
                    key="delete"
                    icon={<DeleteOutlineIcon fontSize="small" />}
                    label={blockedReason ?? 'Delete'}
                    disabled={blockedReason !== null}
                    onClick={() => setDeletingQueue(params.row)}
                  />,
                ]
              },
            },
          ]
        : []),
    ],
    [canManage, ruleCountByQueue],
  )

  return (
    <>
      {queuesQuery.isPending && <LoadingState label="Loading queues…" />}
      {queuesQuery.isError && (
        <ErrorState error={queuesQuery.error} onRetry={() => queuesQuery.refetch()} />
      )}
      {queuesQuery.data?.total === 0 ? (
        <EmptyState
          title="No queues yet"
          description="Create your first queue to start routing conversations."
          action={
            canManage && (
              <Button variant="contained" onClick={onOpenCreate}>
                New queue
              </Button>
            )
          }
        />
      ) : (
        queuesQuery.data && (
          <DataTable
            ariaLabel="Queues"
            rows={queuesQuery.data.items}
            columns={columns}
            getRowId={(row) => row.id}
            rowCount={queuesQuery.data.total}
            page={page}
            pageSize={pageSize}
            onPageChange={setPage}
            onPageSizeChange={setPageSize}
            loading={queuesQuery.isFetching}
          />
        )
      )}

      {canManage && (
        <>
          <QueueCreateDialog open={createOpen} onClose={onCloseCreate} />
          <QueueEditDialog queue={editingQueue} onClose={() => setEditingQueue(null)} />
          <ConfirmDialog
            open={Boolean(deletingQueue)}
            title="Remove queue"
            description={`Remove ${deletingQueue?.name ?? ''}? Conversations currently in this queue keep their history but will no longer route through it. This cannot be undone.`}
            confirmLabel="Remove"
            confirmColor="error"
            isConfirming={deleteMutation.isPending}
            onConfirm={() => {
              if (deletingQueue) {
                deleteMutation.mutate(deletingQueue.id, { onSuccess: () => setDeletingQueue(null) })
              }
            }}
            onClose={() => setDeletingQueue(null)}
          />
        </>
      )}
    </>
  )
}

function conditionsSummary(rule: RoutingRule): string {
  const parts: string[] = []
  if (rule.conditions.channel_type) {
    parts.push(`Channel is ${channelTypeLabel(rule.conditions.channel_type)}`)
  }
  if (rule.conditions.body_contains) {
    parts.push(`Message contains "${rule.conditions.body_contains}"`)
  }
  return parts.length > 0 ? parts.join(' and ') : 'Matches every conversation'
}

function RoutingRulesTab({
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
  const rulesQuery = useRoutingRulesQuery()
  const queuesQuery = useAllQueuesQuery()
  const deleteMutation = useDeleteRoutingRuleMutation()

  const [editingRule, setEditingRule] = useState<RoutingRule | null>(null)
  const [deletingRule, setDeletingRule] = useState<RoutingRule | null>(null)

  const queueNameById = useMemo(() => {
    const map = new Map<string, string>()
    queuesQuery.data?.forEach((queue) => map.set(queue.id, queue.name))
    return map
  }, [queuesQuery.data])

  // Priority-ordered — lower evaluates first, so the table itself doubles
  // as a readable "first match wins" evaluation order, not just a list.
  const sortedRules = useMemo(
    () => [...(rulesQuery.data ?? [])].sort((a, b) => a.priority - b.priority),
    [rulesQuery.data],
  )

  return (
    <>
      {rulesQuery.isPending && <LoadingState label="Loading routing rules…" />}
      {rulesQuery.isError && (
        <ErrorState error={rulesQuery.error} onRetry={() => rulesQuery.refetch()} />
      )}
      {rulesQuery.data && sortedRules.length === 0 && (
        <EmptyState
          title="No routing rules yet"
          description="New conversations with no matching rule aren't routed to a queue automatically."
          action={
            canManage && (
              <Button variant="contained" onClick={onOpenCreate}>
                New routing rule
              </Button>
            )
          }
        />
      )}
      {sortedRules.length > 0 && (
        <TableContainer>
          <Table size="small" aria-label="Routing rules">
            <TableHead>
              <TableRow>
                <TableCell>Priority</TableCell>
                <TableCell>Condition</TableCell>
                <TableCell>Routes to</TableCell>
                <TableCell>Status</TableCell>
                {canManage && <TableCell align="right">Actions</TableCell>}
              </TableRow>
            </TableHead>
            <TableBody>
              {sortedRules.map((rule) => (
                <TableRow key={rule.id}>
                  <TableCell>{rule.priority}</TableCell>
                  <TableCell>{conditionsSummary(rule)}</TableCell>
                  <TableCell>{queueNameById.get(rule.target_queue_id) ?? '—'}</TableCell>
                  <TableCell>
                    <Chip
                      label={rule.is_active ? 'Active' : 'Inactive'}
                      size="small"
                      color={rule.is_active ? 'success' : 'default'}
                    />
                  </TableCell>
                  {canManage && (
                    <TableCell align="right">
                      <Stack direction="row" spacing={0.5} sx={{ justifyContent: 'flex-end' }}>
                        <Tooltip title="Edit">
                          <IconButton
                            size="small"
                            onClick={() => setEditingRule(rule)}
                            aria-label="Edit routing rule"
                          >
                            <EditOutlinedIcon fontSize="small" />
                          </IconButton>
                        </Tooltip>
                        <Tooltip title="Delete">
                          <IconButton
                            size="small"
                            onClick={() => setDeletingRule(rule)}
                            aria-label="Delete routing rule"
                          >
                            <DeleteOutlineIcon fontSize="small" />
                          </IconButton>
                        </Tooltip>
                      </Stack>
                    </TableCell>
                  )}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}

      {canManage && (
        <>
          <RoutingRuleCreateDialog open={createOpen} onClose={onCloseCreate} />
          <RoutingRuleEditDialog rule={editingRule} onClose={() => setEditingRule(null)} />
          <ConfirmDialog
            open={Boolean(deletingRule)}
            title="Remove routing rule"
            description="Remove this routing rule? New conversations matching it will fall through to the next rule instead. This cannot be undone."
            confirmLabel="Remove"
            confirmColor="error"
            isConfirming={deleteMutation.isPending}
            onConfirm={() => {
              if (deletingRule) {
                deleteMutation.mutate(deletingRule.id, { onSuccess: () => setDeletingRule(null) })
              }
            }}
            onClose={() => setDeletingRule(null)}
          />
        </>
      )}
    </>
  )
}

export function QueuesPage() {
  const { hasPermission } = usePermissions()
  const canManage = hasPermission('queues.manage')
  const [tab, setTab] = useState<'queues' | 'rules'>('queues')
  // Owned here (not per-tab) so the "+ New" action can live in the
  // shared PageHeader — stable top-right, same as every other page —
  // instead of moving/disappearing as the tab changes.
  const [queueCreateOpen, setQueueCreateOpen] = useState(false)
  const [ruleCreateOpen, setRuleCreateOpen] = useState(false)

  return (
    <>
      <PageHeader
        title="Queues & Routing"
        description="Decide where new conversations go, and how they're assigned to agents."
        actions={
          canManage &&
          (tab === 'queues' ? (
            <Button
              variant="contained"
              startIcon={<AddIcon />}
              onClick={() => setQueueCreateOpen(true)}
            >
              New queue
            </Button>
          ) : (
            <Button
              variant="contained"
              startIcon={<AddIcon />}
              onClick={() => setRuleCreateOpen(true)}
            >
              New routing rule
            </Button>
          ))
        }
      />

      <Tabs value={tab} onChange={(_event, value) => setTab(value)} sx={{ mb: 2 }}>
        <Tab label="Queues" value="queues" />
        <Tab label="Routing Rules" value="rules" />
      </Tabs>

      {tab === 'queues' && (
        <QueuesTab
          canManage={canManage}
          createOpen={queueCreateOpen}
          onOpenCreate={() => setQueueCreateOpen(true)}
          onCloseCreate={() => setQueueCreateOpen(false)}
        />
      )}
      {tab === 'rules' && (
        <>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            A new conversation is routed to the first active rule (in priority order) whose
            conditions match. Conversations that match no rule aren't routed to a queue.
          </Typography>
          <RoutingRulesTab
            canManage={canManage}
            createOpen={ruleCreateOpen}
            onOpenCreate={() => setRuleCreateOpen(true)}
            onCloseCreate={() => setRuleCreateOpen(false)}
          />
        </>
      )}
    </>
  )
}

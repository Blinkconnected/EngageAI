import { useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { isAxiosError } from 'axios'
import { useTranslation } from 'react-i18next'
import {
  Alert,
  Box,
  Chip,
  FormControlLabel,
  MenuItem,
  Stack,
  Switch,
  Tab,
  Tabs,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Tooltip,
  Typography,
} from '@mui/material'
import AssignmentIndOutlinedIcon from '@mui/icons-material/AssignmentIndOutlined'
import KeyboardOutlinedIcon from '@mui/icons-material/KeyboardOutlined'
import { GridActionsCellItem, type GridColDef } from '@mui/x-data-grid'
import { PageHeader } from '../../shared/components/PageHeader'
import { DataTable } from '../../shared/components/DataTable'
import { EmptyState } from '../../shared/components/EmptyState'
import { extractErrorMessage } from '../../shared/api/errors'
import { formatRelativeTime } from '../../shared/utils/formatRelativeTime'
import { usePermissions } from '../../shared/hooks/usePermissions'
import { useAllChannelsQuery } from '../channels/api'
import { useAllAgentsQuery } from '../agents/api'
import { useAllDepartmentsQuery } from '../departments/api'
import { useAllQueuesQuery } from '../queues/api'
import { useCurrentUserQuery } from '../session/api'
import {
  AutopilotBadge,
  ChannelCell,
  CustomerIdentityCell,
  PriorityBadge,
  SlaIndicator,
} from './ConversationCells'
import { usePickConversationMutation, useConversationsQuery } from './api'
import { CONVERSATION_STATUSES, type Conversation, type ConversationStatus } from './types'

const STATUS_COLOR: Record<ConversationStatus, 'info' | 'warning' | 'success' | 'default'> = {
  open: 'info',
  pending: 'warning',
  resolved: 'success',
  closed: 'default',
}

// Maps each status to the i18n key holding its tab label — the label
// itself can't live in this module-scope map since translation requires
// the `t` function, which is only available inside the component.
const STATUS_TAB_KEY: Record<ConversationStatus, string> = {
  open: 'tabOpen',
  pending: 'tabPending',
  resolved: 'tabResolved',
  closed: 'tabClosed',
}

type FilterMode = 'status' | 'queue'

// A more actively-watched surface than the default status-tab Inbox view —
// an agent switching to "Queue" mode is actively hunting for something to
// pick up, so it polls faster than the Inbox's default 30s (see
// useConversationsQuery's own comment on why 10_000 has no prior-art match
// elsewhere in this codebase).
const QUEUE_MODE_REFETCH_INTERVAL_MS = 10_000

export function InboxPage() {
  const { t, i18n } = useTranslation('conversationsCore')
  const navigate = useNavigate()
  const { hasPermission } = usePermissions()
  const canPick = hasPermission('conversations.pick')

  const tabs: { label: string; value: ConversationStatus | 'all' }[] = [
    { label: t('InboxPage.tabAll'), value: 'all' },
    ...CONVERSATION_STATUSES.map((status) => ({
      label: t(`InboxPage.${STATUS_TAB_KEY[status]}`),
      value: status,
    })),
  ]

  // Filter/queue/page state lives in the URL, not local useState — this is
  // the app's highest-frequency workflow (agents constantly open a
  // conversation from here and come back), and local state was silently
  // reset on every such round trip since InboxPage fully unmounts when
  // navigating to /conversations/:id and back. Query params survive that.
  const [searchParams, setSearchParams] = useSearchParams()

  function updateParams(patch: Record<string, string | null>) {
    setSearchParams(
      (previous) => {
        const next = new URLSearchParams(previous)
        for (const [key, value] of Object.entries(patch)) {
          if (value === null || value === '') next.delete(key)
          else next.set(key, value)
        }
        return next
      },
      { replace: true },
    )
  }

  const filterMode: FilterMode = searchParams.get('mode') === 'queue' ? 'queue' : 'status'
  const statusTab = (searchParams.get('status') as ConversationStatus | 'all' | null) ?? 'open'
  const myConversationsOnly = searchParams.get('mine') === '1'
  const queueFilterId = searchParams.get('queue') ?? ''
  const unassignedOnly = searchParams.get('unassigned') === '1'
  const page = Number(searchParams.get('page') ?? '0')
  const pageSize = Number(searchParams.get('pageSize') ?? '20')
  const apiParams = { page: page + 1, page_size: pageSize }

  const [actionError, setActionError] = useState<string | null>(null)

  const { data: currentUser } = useCurrentUserQuery()
  const agentsQuery = useAllAgentsQuery()
  const departmentsQuery = useAllDepartmentsQuery()
  const queuesQuery = useAllQueuesQuery()
  const myAgentId = agentsQuery.data?.find((agent) => agent.user_id === currentUser?.id)?.id
  // A principal with no Agent record (e.g. an Owner who never became one)
  // has, by definition, zero conversations assigned to them — omitting
  // the filter in that case (the only other option, since sending a
  // non-UUID sentinel would 422) would silently show *everyone's*
  // conversations instead, defeating the whole point of the toggle. Once
  // agents have actually loaded, that's treated as confirmed rather than
  // "still finding out."
  const hasNoAgentProfile =
    filterMode === 'status' && myConversationsOnly && agentsQuery.isFetched && !myAgentId

  const conversationsQuery = useConversationsQuery(
    {
      ...apiParams,
      status_filter: filterMode === 'status' && statusTab !== 'all' ? statusTab : undefined,
      assigned_agent_id: filterMode === 'status' && myConversationsOnly ? myAgentId : undefined,
      queue_id: filterMode === 'queue' && queueFilterId ? queueFilterId : undefined,
      unassigned_only: filterMode === 'queue' ? unassignedOnly : undefined,
    },
    { refetchInterval: filterMode === 'queue' ? QUEUE_MODE_REFETCH_INTERVAL_MS : undefined },
  )
  const channelsQuery = useAllChannelsQuery()
  const pickMutation = usePickConversationMutation()

  const channelById = useMemo(() => {
    const map = new Map<string, { displayName: string; channelType: string }>()
    channelsQuery.data?.forEach((channel) =>
      map.set(channel.id, { displayName: channel.display_name, channelType: channel.channel_type }),
    )
    return map
  }, [channelsQuery.data])

  const agentById = useMemo(() => {
    const map = new Map<string, string>()
    agentsQuery.data?.forEach((agent) => map.set(agent.id, agent.full_name))
    return map
  }, [agentsQuery.data])

  const departmentById = useMemo(() => {
    const map = new Map<string, string>()
    departmentsQuery.data?.forEach((department) => map.set(department.id, department.name))
    return map
  }, [departmentsQuery.data])

  function handlePick(conversationId: string) {
    setActionError(null)
    pickMutation.mutate(conversationId, {
      onError: (error) => {
        setActionError(extractErrorMessage(error, t('InboxPage.pickErrorFallback')))
        // A 409 means someone else claimed it between this page's last
        // poll and the click — the row shown is already stale, so refetch
        // immediately instead of leaving it visible for up to another
        // QUEUE_MODE_REFETCH_INTERVAL_MS.
        if (isAxiosError(error) && error.response?.status === 409) {
          void conversationsQuery.refetch()
        }
      },
    })
  }

  const columns: GridColDef<Conversation>[] = useMemo(
    () => [
      {
        field: 'channel_config_id',
        headerName: t('InboxPage.columnChannel'),
        flex: 1,
        minWidth: 170,
        sortable: false,
        renderCell: (params) => {
          const channel = channelById.get(params.row.channel_config_id)
          return (
            <ChannelCell
              channelType={channel?.channelType ?? null}
              displayName={channel?.displayName ?? null}
              isPending={channelsQuery.isPending}
            />
          )
        },
      },
      {
        field: 'customer_id',
        headerName: t('InboxPage.columnCustomer'),
        flex: 1.4,
        minWidth: 190,
        renderCell: (params) => <CustomerIdentityCell conversation={params.row} />,
      },
      {
        field: 'priority',
        headerName: t('InboxPage.columnPriority'),
        width: 200,
        sortable: false,
        renderCell: (params) => (
          <Stack direction="row" spacing={0.75} sx={{ alignItems: 'center', flexWrap: 'wrap', py: 0.5 }}>
            <PriorityBadge priority={params.row.priority} />
            <SlaIndicator conversation={params.row} />
          </Stack>
        ),
      },
      {
        field: 'status',
        headerName: t('InboxPage.columnStatus'),
        width: 110,
        renderCell: (params) => (
          <Chip
            label={t(`InboxPage.${STATUS_TAB_KEY[params.value as ConversationStatus]}`)}
            size="small"
            color={STATUS_COLOR[params.value as ConversationStatus]}
            variant="outlined"
          />
        ),
      },
      {
        field: 'last_message_at',
        headerName: t('InboxPage.columnLastMessage'),
        width: 130,
        valueGetter: (_value, row) =>
          row.last_message_at ? formatRelativeTime(row.last_message_at) : t('InboxPage.emptyValue'),
      },
      {
        field: 'assigned_agent_id',
        headerName: t('InboxPage.columnAssignedTo'),
        flex: 1,
        minWidth: 170,
        renderCell: (params) => {
          const row = params.row
          let label: string
          if (row.assigned_agent_id) {
            label = agentById.get(row.assigned_agent_id) ?? t('InboxPage.unassignedValue')
          } else if (row.department_id) {
            label = t('InboxPage.departmentSuffixLabel', {
              departmentName: departmentById.get(row.department_id) ?? t('InboxPage.unknownValue'),
            })
          } else {
            label = t('InboxPage.unassignedValue')
          }
          return (
            <Stack direction="row" spacing={0.75} sx={{ alignItems: 'center', minWidth: 0 }}>
              <Typography variant="body2" noWrap title={label}>
                {label}
              </Typography>
              {row.autopilot_active && <AutopilotBadge />}
            </Stack>
          )
        },
      },
      ...(canPick
        ? [
            {
              field: 'actions',
              type: 'actions' as const,
              headerName: t('InboxPage.columnActions'),
              width: 90,
              getActions: (params: { row: Conversation }) => {
                // Only offered on a queued, unassigned conversation — once
                // someone (including this same viewer, via a stale row) has
                // it, picking again would just 409.
                if (!params.row.queue_id || params.row.assigned_agent_id) return []
                return [
                  <GridActionsCellItem
                    key="pick"
                    icon={<AssignmentIndOutlinedIcon fontSize="small" />}
                    label={t('InboxPage.actionPick')}
                    onClick={(event) => {
                      // The grid's own row click navigates to the
                      // conversation — this action instead claims it
                      // in place, so it must not also trigger that.
                      event.stopPropagation()
                      handlePick(params.row.id)
                    }}
                  />,
                ]
              },
            },
          ]
        : []),
    ],
    // handlePick closes over pickMutation/conversationsQuery, which are
    // stable across renders (React Query returns referentially-stable
    // mutate/refetch functions), so it's intentionally left off this list
    // rather than churning column identity every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [channelById, channelsQuery.isPending, agentById, departmentById, canPick, t, i18n.language],
  )

  // Gmail-style j/k row navigation, additive to the grid's own native
  // ArrowUp/ArrowDown/Enter cell-focus handling (left alone rather than
  // reimplemented, so it keeps working exactly as MUI X ships it). j/k
  // move focus to the next/previous row at the currently-focused column
  // (or the first column, the first time), so an agent triaging a queue
  // can move down the list without reaching for the mouse. Ignored while
  // focus is inside a text input (the queue <select>, the "mine"/
  // "unassigned" switches) so typing is never hijacked.
  const gridContainerRef = useRef<HTMLDivElement | null>(null)
  const rows = conversationsQuery.data?.items ?? []

  function handleGridKeyDown(event: ReactKeyboardEvent<HTMLDivElement>) {
    if (event.key !== 'j' && event.key !== 'k') return
    const target = event.target as HTMLElement
    if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable) {
      return
    }

    const focusedCell = document.activeElement?.closest<HTMLElement>('[role="gridcell"]')
    const focusedRow = focusedCell?.closest<HTMLElement>('[data-id]')
    const currentIndex = rows.findIndex((row) => row.id === focusedRow?.getAttribute('data-id'))
    const columnIndex = focusedCell?.getAttribute('data-colindex') ?? '0'

    event.preventDefault()
    const nextIndex =
      event.key === 'j'
        ? Math.min(currentIndex === -1 ? 0 : currentIndex + 1, rows.length - 1)
        : Math.max(currentIndex === -1 ? 0 : currentIndex - 1, 0)
    const nextRow = rows[nextIndex]
    if (!nextRow) return
    const nextRowElement = gridContainerRef.current?.querySelector<HTMLElement>(
      `[data-id="${nextRow.id}"]`,
    )
    const nextCell =
      nextRowElement?.querySelector<HTMLElement>(`[data-colindex="${columnIndex}"]`) ??
      nextRowElement?.querySelector<HTMLElement>('[role="gridcell"]')
    nextCell?.focus()
  }

  return (
    <>
      <PageHeader title={t('InboxPage.pageTitle')} description={t('InboxPage.pageDescription')} />

      {actionError && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setActionError(null)}>
          {actionError}
        </Alert>
      )}

      <Stack
        direction={{ xs: 'column', sm: 'row' }}
        spacing={1}
        sx={{
          mb: 2,
          borderBottom: 1,
          borderColor: 'divider',
          justifyContent: 'space-between',
          alignItems: { sm: 'center' },
          flexWrap: 'wrap',
          rowGap: 1,
        }}
      >
        <Stack
          direction={{ xs: 'column', sm: 'row' }}
          spacing={2}
          sx={{ alignItems: { sm: 'center' } }}
        >
          <ToggleButtonGroup
            size="small"
            value={filterMode}
            exclusive
            onChange={(_event, value: FilterMode | null) => {
              if (value) updateParams({ mode: value === 'status' ? null : value, page: null })
            }}
            aria-label={t('InboxPage.filterModeAriaLabel')}
          >
            <ToggleButton value="status">{t('InboxPage.statusFilterOption')}</ToggleButton>
            <ToggleButton value="queue">{t('InboxPage.queueFilterOption')}</ToggleButton>
          </ToggleButtonGroup>

          {filterMode === 'status' ? (
            <Tabs
              value={statusTab}
              onChange={(_event, value) => {
                updateParams({ status: value === 'open' ? null : value, page: null })
              }}
              variant="scrollable"
              scrollButtons="auto"
            >
              {tabs.map((tab) => (
                <Tab key={tab.value} label={tab.label} value={tab.value} />
              ))}
            </Tabs>
          ) : (
            <TextField
              select
              size="small"
              label={t('InboxPage.queueFieldLabel')}
              value={queueFilterId}
              disabled={queuesQuery.isPending}
              onChange={(event) => {
                updateParams({ queue: event.target.value || null, page: null })
              }}
              sx={{ minWidth: 200 }}
            >
              <MenuItem value="">{t('InboxPage.allQueuesOption')}</MenuItem>
              {queuesQuery.data?.map((queue) => (
                <MenuItem key={queue.id} value={queue.id}>
                  {queue.name}
                </MenuItem>
              ))}
            </TextField>
          )}
        </Stack>

        {filterMode === 'status' ? (
          <FormControlLabel
            sx={{ mr: 1 }}
            control={
              <Switch
                checked={myConversationsOnly}
                onChange={(event) => {
                  updateParams({ mine: event.target.checked ? '1' : null, page: null })
                }}
              />
            }
            label={t('InboxPage.myConversationsOnlyLabel')}
          />
        ) : (
          <FormControlLabel
            sx={{ mr: 1 }}
            control={
              <Switch
                checked={unassignedOnly}
                onChange={(event) => {
                  updateParams({ unassigned: event.target.checked ? '1' : null, page: null })
                }}
              />
            }
            label={t('InboxPage.unassignedOnlyLabel')}
          />
        )}
      </Stack>

      {hasNoAgentProfile ? (
        <EmptyState
          title={t('InboxPage.noAgentProfileTitle')}
          description={t('InboxPage.noAgentProfileDescription')}
        />
      ) : !conversationsQuery.isError && conversationsQuery.data?.total === 0 ? (
        <EmptyState
          title={t('InboxPage.noConversationsTitle')}
          description={t('InboxPage.noConversationsDescription')}
        />
      ) : (
        <Box
          ref={gridContainerRef}
          onKeyDown={handleGridKeyDown}
          sx={{ display: 'flex', flexDirection: 'column', gap: 0.5 }}
        >
          <Tooltip title={t('InboxPage.keyboardShortcutsTooltip')}>
            <Stack
              direction="row"
              spacing={0.5}
              sx={{ alignItems: 'center', alignSelf: 'flex-end', color: 'text.secondary' }}
            >
              <KeyboardOutlinedIcon fontSize="inherit" />
              <Typography variant="caption">{t('InboxPage.keyboardShortcutsHint')}</Typography>
            </Stack>
          </Tooltip>
          <DataTable
            ariaLabel={t('InboxPage.dataTableAriaLabel')}
            rows={rows}
            columns={columns}
            getRowId={(row) => row.id}
            rowCount={conversationsQuery.data?.total ?? 0}
            page={page}
            pageSize={pageSize}
            onPageChange={(newPage) => updateParams({ page: newPage === 0 ? null : String(newPage) })}
            onPageSizeChange={(newPageSize) =>
              updateParams({ pageSize: newPageSize === 20 ? null : String(newPageSize), page: null })
            }
            loading={conversationsQuery.isFetching}
            onRowClick={(row) => navigate(`/conversations/${row.id}`)}
            error={conversationsQuery.isError ? conversationsQuery.error : undefined}
            onRetry={() => void conversationsQuery.refetch()}
          />
        </Box>
      )}
    </>
  )
}

import { useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { isAxiosError } from 'axios'
import { useTranslation } from 'react-i18next'
import {
  Alert,
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
} from '@mui/material'
import AssignmentIndOutlinedIcon from '@mui/icons-material/AssignmentIndOutlined'
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
import { CustomerNameCell } from './ConversationCells'
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
    const map = new Map<string, string>()
    channelsQuery.data?.forEach((channel) => map.set(channel.id, channel.display_name))
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
        field: 'customer_id',
        headerName: t('InboxPage.columnCustomer'),
        flex: 1,
        minWidth: 160,
        renderCell: (params) => <CustomerNameCell customerId={params.row.customer_id} />,
      },
      {
        field: 'channel_config_id',
        headerName: t('InboxPage.columnChannel'),
        flex: 1,
        minWidth: 140,
        valueGetter: (_value, row) => {
          const name = channelById.get(row.channel_config_id)
          return name ?? t('InboxPage.emptyValue')
        },
      },
      {
        field: 'status',
        headerName: t('InboxPage.columnStatus'),
        width: 120,
        renderCell: (params) => (
          <Chip
            label={t(`InboxPage.${STATUS_TAB_KEY[params.value as ConversationStatus]}`)}
            size="small"
            color={STATUS_COLOR[params.value as ConversationStatus]}
          />
        ),
      },
      {
        field: 'last_message_at',
        headerName: t('InboxPage.columnLastMessage'),
        width: 150,
        valueGetter: (_value, row) =>
          row.last_message_at ? formatRelativeTime(row.last_message_at) : t('InboxPage.emptyValue'),
      },
      {
        field: 'assigned_agent_id',
        headerName: t('InboxPage.columnAssignedTo'),
        flex: 1,
        minWidth: 150,
        valueGetter: (_value, row) => {
          if (row.assigned_agent_id) {
            return agentById.get(row.assigned_agent_id) ?? t('InboxPage.unassignedValue')
          }
          if (row.department_id) {
            return t('InboxPage.departmentSuffixLabel', {
              departmentName: departmentById.get(row.department_id) ?? t('InboxPage.unknownValue'),
            })
          }
          return t('InboxPage.unassignedValue')
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
    [channelById, agentById, departmentById, canPick, t, i18n.language],
  )

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
      ) : conversationsQuery.data?.total === 0 ? (
        <EmptyState
          title={t('InboxPage.noConversationsTitle')}
          description={t('InboxPage.noConversationsDescription')}
        />
      ) : (
        <DataTable
          ariaLabel={t('InboxPage.dataTableAriaLabel')}
          rows={conversationsQuery.data?.items ?? []}
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
        />
      )}
    </>
  )
}

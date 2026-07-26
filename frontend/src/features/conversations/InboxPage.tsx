import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { isAxiosError } from 'axios'
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
import { usePaginationParams } from '../../shared/api/pagination'
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

const TABS: { label: string; value: ConversationStatus | 'all' }[] = [
  { label: 'All', value: 'all' },
  ...CONVERSATION_STATUSES.map((status) => ({
    label: status[0].toUpperCase() + status.slice(1),
    value: status,
  })),
]

type FilterMode = 'status' | 'queue'

// A more actively-watched surface than the default status-tab Inbox view —
// an agent switching to "Queue" mode is actively hunting for something to
// pick up, so it polls faster than the Inbox's default 30s (see
// useConversationsQuery's own comment on why 10_000 has no prior-art match
// elsewhere in this codebase).
const QUEUE_MODE_REFETCH_INTERVAL_MS = 10_000

export function InboxPage() {
  const navigate = useNavigate()
  const { hasPermission } = usePermissions()
  const canPick = hasPermission('conversations.pick')

  const [filterMode, setFilterMode] = useState<FilterMode>('status')
  const [statusTab, setStatusTab] = useState<ConversationStatus | 'all'>('open')
  const [myConversationsOnly, setMyConversationsOnly] = useState(false)
  const [queueFilterId, setQueueFilterId] = useState('')
  const [unassignedOnly, setUnassignedOnly] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const { page, pageSize, setPage, setPageSize, apiParams } = usePaginationParams()

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
        setActionError(extractErrorMessage(error, 'Could not pick up this conversation.'))
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
        headerName: 'Customer',
        flex: 1,
        minWidth: 160,
        renderCell: (params) => <CustomerNameCell customerId={params.row.customer_id} />,
      },
      {
        field: 'channel_config_id',
        headerName: 'Channel',
        flex: 1,
        minWidth: 140,
        valueGetter: (_value, row) => {
          const name = channelById.get(row.channel_config_id)
          return name ?? '—'
        },
      },
      {
        field: 'status',
        headerName: 'Status',
        width: 120,
        renderCell: (params) => (
          <Chip
            label={params.value}
            size="small"
            color={STATUS_COLOR[params.value as ConversationStatus]}
          />
        ),
      },
      {
        field: 'last_message_at',
        headerName: 'Last message',
        width: 150,
        valueGetter: (_value, row) =>
          row.last_message_at ? formatRelativeTime(row.last_message_at) : '—',
      },
      {
        field: 'assigned_agent_id',
        headerName: 'Assigned to',
        flex: 1,
        minWidth: 150,
        valueGetter: (_value, row) => {
          if (row.assigned_agent_id) return agentById.get(row.assigned_agent_id) ?? 'Unassigned'
          if (row.department_id) {
            return `${departmentById.get(row.department_id) ?? 'Unknown'} (department)`
          }
          return 'Unassigned'
        },
      },
      ...(canPick
        ? [
            {
              field: 'actions',
              type: 'actions' as const,
              headerName: 'Actions',
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
                    label="Pick"
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
    [channelById, agentById, departmentById, canPick],
  )

  return (
    <>
      <PageHeader title="Inbox" description="Conversations across every connected channel." />

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
              if (value) {
                setFilterMode(value)
                setPage(0)
              }
            }}
            aria-label="Filter mode"
          >
            <ToggleButton value="status">Status</ToggleButton>
            <ToggleButton value="queue">Queue</ToggleButton>
          </ToggleButtonGroup>

          {filterMode === 'status' ? (
            <Tabs
              value={statusTab}
              onChange={(_event, value) => {
                setStatusTab(value)
                setPage(0)
              }}
            >
              {TABS.map((tab) => (
                <Tab key={tab.value} label={tab.label} value={tab.value} />
              ))}
            </Tabs>
          ) : (
            <TextField
              select
              size="small"
              label="Queue"
              value={queueFilterId}
              disabled={queuesQuery.isPending}
              onChange={(event) => {
                setQueueFilterId(event.target.value)
                setPage(0)
              }}
              sx={{ minWidth: 200 }}
            >
              <MenuItem value="">All queues</MenuItem>
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
                  setMyConversationsOnly(event.target.checked)
                  setPage(0)
                }}
              />
            }
            label="My conversations only"
          />
        ) : (
          <FormControlLabel
            sx={{ mr: 1 }}
            control={
              <Switch
                checked={unassignedOnly}
                onChange={(event) => {
                  setUnassignedOnly(event.target.checked)
                  setPage(0)
                }}
              />
            }
            label="Unassigned only"
          />
        )}
      </Stack>

      {hasNoAgentProfile ? (
        <EmptyState
          title="No agent profile"
          description="Your account isn't set up as an agent, so no conversations can be assigned to you."
        />
      ) : conversationsQuery.data?.total === 0 ? (
        <EmptyState
          title="No conversations here"
          description="New conversations will appear here as customers reach out on your connected channels."
        />
      ) : (
        <DataTable
          ariaLabel="Inbox"
          rows={conversationsQuery.data?.items ?? []}
          columns={columns}
          getRowId={(row) => row.id}
          rowCount={conversationsQuery.data?.total ?? 0}
          page={page}
          pageSize={pageSize}
          onPageChange={setPage}
          onPageSizeChange={setPageSize}
          loading={conversationsQuery.isFetching}
          onRowClick={(row) => navigate(`/conversations/${row.id}`)}
        />
      )}
    </>
  )
}

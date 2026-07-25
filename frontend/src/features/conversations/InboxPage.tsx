import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Chip, FormControlLabel, Stack, Switch, Tab, Tabs } from '@mui/material'
import type { GridColDef } from '@mui/x-data-grid'
import { PageHeader } from '../../shared/components/PageHeader'
import { DataTable } from '../../shared/components/DataTable'
import { EmptyState } from '../../shared/components/EmptyState'
import { usePaginationParams } from '../../shared/api/pagination'
import { formatRelativeTime } from '../../shared/utils/formatRelativeTime'
import { useAllChannelsQuery } from '../channels/api'
import { useAllAgentsQuery } from '../agents/api'
import { useAllDepartmentsQuery } from '../departments/api'
import { useCurrentUserQuery } from '../session/api'
import { CustomerNameCell } from './ConversationCells'
import { useConversationsQuery } from './api'
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

export function InboxPage() {
  const navigate = useNavigate()
  const [statusTab, setStatusTab] = useState<ConversationStatus | 'all'>('open')
  const [myConversationsOnly, setMyConversationsOnly] = useState(false)
  const { page, pageSize, setPage, setPageSize, apiParams } = usePaginationParams()

  const { data: currentUser } = useCurrentUserQuery()
  const agentsQuery = useAllAgentsQuery()
  const departmentsQuery = useAllDepartmentsQuery()
  const myAgentId = agentsQuery.data?.find((agent) => agent.user_id === currentUser?.id)?.id
  // A principal with no Agent record (e.g. an Owner who never became one)
  // has, by definition, zero conversations assigned to them — omitting
  // the filter in that case (the only other option, since sending a
  // non-UUID sentinel would 422) would silently show *everyone's*
  // conversations instead, defeating the whole point of the toggle. Once
  // agents have actually loaded, that's treated as confirmed rather than
  // "still finding out."
  const hasNoAgentProfile = myConversationsOnly && agentsQuery.isFetched && !myAgentId

  const conversationsQuery = useConversationsQuery({
    ...apiParams,
    status_filter: statusTab === 'all' ? undefined : statusTab,
    assigned_agent_id: myConversationsOnly ? myAgentId : undefined,
  })
  const channelsQuery = useAllChannelsQuery()

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
    ],
    [channelById, agentById, departmentById],
  )

  return (
    <>
      <PageHeader title="Inbox" description="Conversations across every connected channel." />

      <Stack
        direction={{ xs: 'column', sm: 'row' }}
        spacing={1}
        sx={{
          mb: 2,
          borderBottom: 1,
          borderColor: 'divider',
          justifyContent: 'space-between',
          alignItems: { sm: 'center' },
        }}
      >
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

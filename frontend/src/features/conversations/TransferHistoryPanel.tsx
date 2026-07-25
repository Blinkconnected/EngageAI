import { useMemo } from 'react'
import { Chip, Paper, Stack, Typography } from '@mui/material'
import PersonOutlinedIcon from '@mui/icons-material/PersonOutlined'
import ApartmentOutlinedIcon from '@mui/icons-material/ApartmentOutlined'
import { LoadingState } from '../../shared/components/LoadingState'
import { ErrorState } from '../../shared/components/ErrorState'
import { EmptyState } from '../../shared/components/EmptyState'
import { formatRelativeTime } from '../../shared/utils/formatRelativeTime'
import { useAllAgentsQuery } from '../agents/api'
import { useAllDepartmentsQuery } from '../departments/api'
import { useCurrentUserQuery } from '../session/api'
import { useTransfersQuery } from './api'
import type { ConversationTransfer } from './types'

export function TransferHistoryPanel({ conversationId }: { conversationId: string }) {
  const transfersQuery = useTransfersQuery(conversationId, { page: 1, page_size: 50 })
  const agentsQuery = useAllAgentsQuery()
  const departmentsQuery = useAllDepartmentsQuery()
  const { data: currentUser } = useCurrentUserQuery()

  const agentNameById = useMemo(() => {
    const map = new Map<string, string>()
    agentsQuery.data?.forEach((agent) => map.set(agent.id, agent.full_name))
    return map
  }, [agentsQuery.data])

  const departmentNameById = useMemo(() => {
    const map = new Map<string, string>()
    departmentsQuery.data?.forEach((department) => map.set(department.id, department.name))
    return map
  }, [departmentsQuery.data])

  function describeTarget(transfer: ConversationTransfer): string {
    if (transfer.target_type === 'agent' && transfer.to_agent_id) {
      return agentNameById.get(transfer.to_agent_id) ?? 'an agent'
    }
    if (transfer.target_type === 'department' && transfer.to_department_id) {
      return `${departmentNameById.get(transfer.to_department_id) ?? 'a department'} department`
    }
    return 'a queue'
  }

  return (
    <Stack sx={{ flexGrow: 1, overflowY: 'auto', p: 2 }} spacing={2}>
      {transfersQuery.isPending && <LoadingState label="Loading transfer history…" />}
      {transfersQuery.isError && (
        <ErrorState error={transfersQuery.error} onRetry={() => transfersQuery.refetch()} />
      )}
      {transfersQuery.data?.total === 0 && (
        <EmptyState
          title="No transfers yet"
          description="This conversation has never been transferred to another agent or department."
        />
      )}
      {transfersQuery.data?.items.map((transfer) => (
        <Paper key={transfer.id} variant="outlined" sx={{ p: 1.5 }}>
          <Stack direction="row" spacing={1} sx={{ alignItems: 'flex-start' }}>
            {transfer.target_type === 'department' ? (
              <ApartmentOutlinedIcon color="action" fontSize="small" />
            ) : (
              <PersonOutlinedIcon color="action" fontSize="small" />
            )}
            <Stack sx={{ flexGrow: 1, minWidth: 0 }} spacing={0.5}>
              <Typography variant="body2">
                Transferred to <strong>{describeTarget(transfer)}</strong>
                {transfer.transferred_by_user_id === currentUser?.id ? ' by you' : ''}
              </Typography>
              {transfer.note && (
                <Typography variant="body2" color="text.secondary" sx={{ fontStyle: 'italic' }}>
                  "{transfer.note}"
                </Typography>
              )}
              <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
                <Typography variant="caption" color="text.secondary">
                  {formatRelativeTime(transfer.created_at)}
                </Typography>
                {!transfer.recipient_was_online && transfer.target_type !== 'queue' && (
                  <Chip label="Recipient was offline" size="small" variant="outlined" />
                )}
              </Stack>
            </Stack>
          </Stack>
        </Paper>
      ))}
    </Stack>
  )
}

import { useMemo, useState } from 'react'
import { Button, Chip } from '@mui/material'
import AddIcon from '@mui/icons-material/Add'
import EditOutlinedIcon from '@mui/icons-material/EditOutlined'
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutlined'
import HistoryOutlinedIcon from '@mui/icons-material/HistoryOutlined'
import { GridActionsCellItem, type GridColDef } from '@mui/x-data-grid'
import { PageHeader } from '../../shared/components/PageHeader'
import { DataTable } from '../../shared/components/DataTable'
import { ConfirmDialog } from '../../shared/components/ConfirmDialog'
import { EmptyState } from '../../shared/components/EmptyState'
import { usePaginationParams } from '../../shared/api/pagination'
import { usePermissions } from '../../shared/hooks/usePermissions'
import { ChannelCreateDialog } from './ChannelCreateDialog'
import { ChannelEditDialog } from './ChannelEditDialog'
import { ChannelHealthBadge } from './ChannelHealthBadge'
import { ConnectionLogsDialog } from './ConnectionLogsDialog'
import { useChannelsQuery, useDeleteChannelMutation } from './api'
import { channelTypeLabel, type ChannelConfig } from './types'

export function ChannelsPage() {
  const { hasPermission } = usePermissions()
  const canManage = hasPermission('channels.manage')

  const { page, pageSize, setPage, setPageSize, apiParams } = usePaginationParams()
  const channelsQuery = useChannelsQuery(apiParams)

  const [createOpen, setCreateOpen] = useState(false)
  const [editingChannel, setEditingChannel] = useState<ChannelConfig | null>(null)
  const [deletingChannel, setDeletingChannel] = useState<ChannelConfig | null>(null)
  const [logsChannel, setLogsChannel] = useState<ChannelConfig | null>(null)
  const deleteMutation = useDeleteChannelMutation()

  const columns: GridColDef<ChannelConfig>[] = useMemo(
    () => [
      { field: 'display_name', headerName: 'Name', flex: 1, minWidth: 180 },
      {
        field: 'channel_type',
        headerName: 'Type',
        flex: 1,
        minWidth: 160,
        valueGetter: (_value, row) => channelTypeLabel(row.channel_type),
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
      {
        field: 'last_health_status',
        headerName: 'Connection',
        width: 150,
        sortable: false,
        renderCell: (params) => <ChannelHealthBadge channel={params.row} />,
      },
      {
        field: 'actions',
        type: 'actions' as const,
        headerName: 'Actions',
        width: canManage ? 140 : 60,
        getActions: (params: { row: ChannelConfig }) => [
          <GridActionsCellItem
            key="logs"
            icon={<HistoryOutlinedIcon fontSize="small" />}
            label="Connection logs"
            onClick={() => setLogsChannel(params.row)}
          />,
          ...(canManage
            ? [
                <GridActionsCellItem
                  key="edit"
                  icon={<EditOutlinedIcon fontSize="small" />}
                  label="Edit"
                  onClick={() => setEditingChannel(params.row)}
                />,
                <GridActionsCellItem
                  key="delete"
                  icon={<DeleteOutlineIcon fontSize="small" />}
                  label="Delete"
                  onClick={() => setDeletingChannel(params.row)}
                />,
              ]
            : []),
        ],
      },
    ],
    [canManage],
  )

  return (
    <>
      <PageHeader
        title="Channels"
        description="Connect WhatsApp and other channels your customers reach you on."
        actions={
          canManage && (
            <Button variant="contained" startIcon={<AddIcon />} onClick={() => setCreateOpen(true)}>
              Connect channel
            </Button>
          )
        }
      />

      {channelsQuery.data?.total === 0 ? (
        <EmptyState
          title="No channels connected yet"
          description="Connect WhatsApp or another channel to start receiving conversations."
          action={
            canManage && (
              <Button variant="contained" onClick={() => setCreateOpen(true)}>
                Connect channel
              </Button>
            )
          }
        />
      ) : (
        <DataTable
          ariaLabel="Channels"
          rows={channelsQuery.data?.items ?? []}
          columns={columns}
          getRowId={(row) => row.id}
          rowCount={channelsQuery.data?.total ?? 0}
          page={page}
          pageSize={pageSize}
          onPageChange={setPage}
          onPageSizeChange={setPageSize}
          loading={channelsQuery.isFetching}
          error={channelsQuery.error}
          onRetry={() => channelsQuery.refetch()}
        />
      )}

      {canManage && (
        <>
          <ChannelCreateDialog open={createOpen} onClose={() => setCreateOpen(false)} />
          <ChannelEditDialog channel={editingChannel} onClose={() => setEditingChannel(null)} />
          <ConfirmDialog
            open={Boolean(deletingChannel)}
            title="Disconnect channel"
            description={`Disconnect ${deletingChannel?.display_name ?? ''}? Its webhook will stop receiving messages immediately.`}
            confirmLabel="Disconnect"
            confirmColor="error"
            isConfirming={deleteMutation.isPending}
            onConfirm={() => {
              if (deletingChannel) {
                deleteMutation.mutate(deletingChannel.id, {
                  onSuccess: () => setDeletingChannel(null),
                })
              }
            }}
            onClose={() => setDeletingChannel(null)}
          />
        </>
      )}
      <ConnectionLogsDialog channel={logsChannel} onClose={() => setLogsChannel(null)} />
    </>
  )
}

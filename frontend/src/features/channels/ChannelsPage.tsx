import { useMemo, useState } from 'react'
import { Button, Chip } from '@mui/material'
import AddIcon from '@mui/icons-material/Add'
import EditOutlinedIcon from '@mui/icons-material/EditOutlined'
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutlined'
import HistoryOutlinedIcon from '@mui/icons-material/HistoryOutlined'
import { GridActionsCellItem, type GridColDef } from '@mui/x-data-grid'
import { useTranslation } from 'react-i18next'
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
  const { t, i18n } = useTranslation('channelsCore')
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
      { field: 'display_name', headerName: t('ChannelsPage.nameColumn'), flex: 1, minWidth: 180 },
      {
        field: 'channel_type',
        headerName: t('ChannelsPage.typeColumn'),
        flex: 1,
        minWidth: 160,
        valueGetter: (_value, row) => channelTypeLabel(row.channel_type),
      },
      {
        field: 'is_active',
        headerName: t('ChannelsPage.statusColumn'),
        width: 110,
        renderCell: (params) => (
          <Chip
            label={params.value ? t('ChannelsPage.activeLabel') : t('ChannelsPage.inactiveLabel')}
            size="small"
            color={params.value ? 'success' : 'default'}
          />
        ),
      },
      {
        field: 'last_health_status',
        headerName: t('ChannelsPage.connectionColumn'),
        width: 150,
        sortable: false,
        renderCell: (params) => <ChannelHealthBadge channel={params.row} />,
      },
      {
        field: 'actions',
        type: 'actions' as const,
        headerName: t('ChannelsPage.actionsColumn'),
        width: canManage ? 140 : 60,
        getActions: (params: { row: ChannelConfig }) => [
          <GridActionsCellItem
            key="logs"
            icon={<HistoryOutlinedIcon fontSize="small" />}
            label={t('ChannelsPage.connectionLogsAction')}
            onClick={() => setLogsChannel(params.row)}
          />,
          ...(canManage
            ? [
                <GridActionsCellItem
                  key="edit"
                  icon={<EditOutlinedIcon fontSize="small" />}
                  label={t('ChannelsPage.editAction')}
                  onClick={() => setEditingChannel(params.row)}
                />,
                <GridActionsCellItem
                  key="delete"
                  icon={<DeleteOutlineIcon fontSize="small" />}
                  label={t('ChannelsPage.deleteAction')}
                  onClick={() => setDeletingChannel(params.row)}
                />,
              ]
            : []),
        ],
      },
    ],
    // i18n.language isn't referenced by name in this callback, but t()'s
    // output depends on it, so it must stay a real dependency.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [canManage, t, i18n.language],
  )

  return (
    <>
      <PageHeader
        title={t('ChannelsPage.pageTitle')}
        description={t('ChannelsPage.pageDescription')}
        actions={
          canManage && (
            <Button variant="contained" startIcon={<AddIcon />} onClick={() => setCreateOpen(true)}>
              {t('ChannelsPage.connectChannelButton')}
            </Button>
          )
        }
      />

      {channelsQuery.data?.total === 0 ? (
        <EmptyState
          title={t('ChannelsPage.emptyStateTitle')}
          description={t('ChannelsPage.emptyStateDescription')}
          action={
            canManage && (
              <Button variant="contained" onClick={() => setCreateOpen(true)}>
                {t('ChannelsPage.connectChannelButton')}
              </Button>
            )
          }
        />
      ) : (
        <DataTable
          ariaLabel={t('ChannelsPage.gridAriaLabel')}
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
            title={t('ChannelsPage.disconnectDialogTitle')}
            description={t('ChannelsPage.disconnectDialogDescription', {
              name: deletingChannel?.display_name ?? '',
            })}
            confirmLabel={t('ChannelsPage.disconnectButton')}
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

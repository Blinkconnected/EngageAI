import { useMemo, useState } from 'react'
import { Card, CardContent, MenuItem, Stack, TextField, Typography } from '@mui/material'
import { BarChart } from '@mui/x-charts/BarChart'
import type { GridColDef } from '@mui/x-data-grid'
import { useTranslation } from 'react-i18next'
import { EmptyState } from '../../../shared/components/EmptyState'
import { ErrorState } from '../../../shared/components/ErrorState'
import { LoadingState } from '../../../shared/components/LoadingState'
import { channelTypeLabel } from '../../channels/types'
import { useConversationsReportQuery } from '../api'
import { ReportDataGrid } from '../ReportDataGrid'
import { ReportExportButtons } from '../ReportExportButtons'
import type { ConversationStatsRow, DateRange } from '../types'

function aggregateByChannel(rows: ConversationStatsRow[]) {
  const totals = new Map<string, { opened: number; closed: number; resolved: number }>()
  for (const row of rows) {
    const current = totals.get(row.channel_type) ?? { opened: 0, closed: 0, resolved: 0 }
    totals.set(row.channel_type, {
      opened: current.opened + row.opened,
      closed: current.closed + row.closed,
      resolved: current.resolved + row.resolved,
    })
  }
  return Array.from(totals.entries()).map(([channel_type, values]) => ({ channel_type, ...values }))
}

export function ConversationsReportPanel({ range }: { range: DateRange }) {
  const { t, i18n } = useTranslation('reportsPanels')
  const query = useConversationsReportQuery(range)
  const [channelFilter, setChannelFilter] = useState('all')

  const columns: GridColDef<ConversationStatsRow>[] = useMemo(
    () => [
      { field: 'stat_date', headerName: t('ConversationsReportPanel.columns.date'), flex: 1 },
      {
        field: 'channel_type',
        headerName: t('ConversationsReportPanel.columns.channel'),
        flex: 1,
        valueFormatter: (value: string) => channelTypeLabel(value),
      },
      {
        field: 'opened',
        headerName: t('ConversationsReportPanel.columns.opened'),
        flex: 1,
        type: 'number',
      },
      {
        field: 'closed',
        headerName: t('ConversationsReportPanel.columns.closed'),
        flex: 1,
        type: 'number',
      },
      {
        field: 'resolved',
        headerName: t('ConversationsReportPanel.columns.resolved'),
        flex: 1,
        type: 'number',
      },
      {
        field: 'first_response_breached',
        headerName: t('ConversationsReportPanel.columns.firstRespBreaches'),
        flex: 1,
        type: 'number',
      },
      {
        field: 'resolution_breached',
        headerName: t('ConversationsReportPanel.columns.resolutionBreaches'),
        flex: 1,
        type: 'number',
      },
    ],
    // i18n.language isn't referenced by name in this callback, but t()'s
    // output depends on it, so it must stay a real dependency.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [t, i18n.language],
  )

  const channels = useMemo(
    () => Array.from(new Set((query.data ?? []).map((row) => row.channel_type))).sort(),
    [query.data],
  )
  const filteredRows = useMemo(
    () =>
      channelFilter === 'all'
        ? (query.data ?? [])
        : (query.data ?? []).filter((row) => row.channel_type === channelFilter),
    [query.data, channelFilter],
  )

  if (query.isPending) return <LoadingState label={t('ConversationsReportPanel.loadingLabel')} />
  if (query.isError) return <ErrorState error={query.error} onRetry={() => query.refetch()} />

  const chartData = aggregateByChannel(filteredRows)

  return (
    <>
      <Stack
        direction={{ xs: 'column', sm: 'row' }}
        spacing={2}
        sx={{ justifyContent: 'space-between', alignItems: { sm: 'center' }, mb: 2 }}
      >
        <TextField
          select
          size="small"
          label={t('ConversationsReportPanel.channelSelectLabel')}
          value={channelFilter}
          onChange={(event) => setChannelFilter(event.target.value)}
          sx={{ minWidth: 180 }}
        >
          <MenuItem value="all">{t('ConversationsReportPanel.allChannelsOption')}</MenuItem>
          {channels.map((channel) => (
            <MenuItem key={channel} value={channel}>
              {channelTypeLabel(channel)}
            </MenuItem>
          ))}
        </TextField>
        <Stack spacing={0.5} sx={{ alignItems: { xs: 'flex-start', sm: 'flex-end' } }}>
          <ReportExportButtons
            path="/reports/conversations"
            range={range}
            fallbackFilenameBase="conversations-report"
          />
          {channelFilter !== 'all' && (
            <Typography variant="caption" color="text.secondary">
              {t('ConversationsReportPanel.exportsNotice', {
                channel: channelTypeLabel(channelFilter),
              })}
            </Typography>
          )}
        </Stack>
      </Stack>

      {filteredRows.length === 0 ? (
        <EmptyState
          title={t('ConversationsReportPanel.emptyTitle')}
          description={t('ConversationsReportPanel.emptyDescription')}
        />
      ) : (
        <>
          <Card variant="outlined" sx={{ mb: 3 }}>
            <CardContent>
              <Typography variant="subtitle1" component="h2" sx={{ fontWeight: 600 }} gutterBottom>
                {t('ConversationsReportPanel.chartTitle')}
              </Typography>
              <BarChart
                height={300}
                dataset={chartData}
                xAxis={[
                  {
                    dataKey: 'channel_type',
                    scaleType: 'band',
                    valueFormatter: (value: string) => channelTypeLabel(value),
                  },
                ]}
                series={[
                  { dataKey: 'opened', label: t('ConversationsReportPanel.seriesOpened') },
                  { dataKey: 'closed', label: t('ConversationsReportPanel.seriesClosed') },
                  { dataKey: 'resolved', label: t('ConversationsReportPanel.seriesResolved') },
                ]}
              />
            </CardContent>
          </Card>
          <ReportDataGrid
            rows={filteredRows}
            columns={columns}
            getRowId={(row) => `${row.stat_date}-${row.channel_type}`}
            ariaLabel={t('ConversationsReportPanel.gridAriaLabel')}
          />
        </>
      )}
    </>
  )
}

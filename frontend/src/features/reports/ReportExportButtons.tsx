import PictureAsPdfOutlinedIcon from '@mui/icons-material/PictureAsPdfOutlined'
import TableChartOutlinedIcon from '@mui/icons-material/TableChartOutlined'
import { useTranslation } from 'react-i18next'
import { Alert, Button, Stack } from '@mui/material'
import { useReportExport } from './api'
import type { DateRange } from './types'

interface ReportExportButtonsProps {
  path: string
  range: DateRange
  fallbackFilenameBase: string
}

/**
 * PDF/Excel export, shared by every date-ranged report panel (all except
 * agent-dashboard/live-dashboard, which the backend doesn't support export
 * on). The export always reflects the full date range regardless of any
 * client-side-only filter a panel applies to its on-screen table/chart.
 */
export function ReportExportButtons({
  path,
  range,
  fallbackFilenameBase,
}: ReportExportButtonsProps) {
  const { t } = useTranslation('reportsCore')
  const { exportReport, isExporting, error } = useReportExport()

  return (
    <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
      <Button
        size="small"
        variant="outlined"
        startIcon={<PictureAsPdfOutlinedIcon />}
        disabled={isExporting}
        onClick={() => exportReport(path, range, 'pdf', `${fallbackFilenameBase}.pdf`)}
      >
        {t('ReportExportButtons.pdfButton')}
      </Button>
      <Button
        size="small"
        variant="outlined"
        startIcon={<TableChartOutlinedIcon />}
        disabled={isExporting}
        onClick={() => exportReport(path, range, 'xlsx', `${fallbackFilenameBase}.xlsx`)}
      >
        {t('ReportExportButtons.excelButton')}
      </Button>
      {error != null && (
        <Alert severity="error" sx={{ py: 0 }}>
          {t('ReportExportButtons.exportFailedMessage')}
        </Alert>
      )}
    </Stack>
  )
}

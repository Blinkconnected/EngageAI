import { useTranslation } from 'react-i18next'
import {
  Card,
  CardContent,
  Chip,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableRow,
  Typography,
} from '@mui/material'
import { formatRelativeTime } from '../../shared/utils/formatRelativeTime'
import type { ErpSyncedRecord } from './types'

/** ERPNext data is doctype-agnostic by design (see docs/architecture/
 * erp-integration.md) — there's no fixed schema per doctype, so this
 * renders whatever key/value pairs the raw document actually has rather
 * than assuming any particular field set. */
export function ErpRecordCard({ record }: { record: ErpSyncedRecord }) {
  const { t } = useTranslation('erp')
  const entries = Object.entries(record.data)

  return (
    <Card variant="outlined">
      <CardContent>
        <Stack direction="row" spacing={1} sx={{ alignItems: 'center', mb: 1 }}>
          <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
            {record.external_name}
          </Typography>
          <Chip label={record.doctype} size="small" />
        </Stack>
        {entries.length > 0 && (
          <Table size="small">
            <TableBody>
              {entries.map(([key, value]) => (
                <TableRow key={key}>
                  <TableCell sx={{ fontWeight: 600, whiteSpace: 'nowrap', border: 0 }}>
                    {key}
                  </TableCell>
                  <TableCell sx={{ wordBreak: 'break-word', border: 0 }}>
                    {typeof value === 'object' && value !== null
                      ? JSON.stringify(value)
                      : String(value)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
        <Typography variant="caption" color="text.secondary">
          {t('ErpRecordCard.syncedLabel', { time: formatRelativeTime(record.synced_at) })}
        </Typography>
      </CardContent>
    </Card>
  )
}

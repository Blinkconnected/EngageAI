import {
  Box,
  LinearProgress,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Typography,
} from '@mui/material'
import { useTranslation } from 'react-i18next'
import {
  formatEstimate,
  formatPercent,
  formatQuantity,
  formatUnitPrice,
  type CurrencyFormat,
} from './money'
import type { MetricCost } from './types'

/**
 * "What is generating my costs" — the third of the five questions.
 *
 * Rows arrive sorted by cost, largest first, and the share bar makes the
 * distribution readable without doing the division by eye. The allowance
 * column is here because a customer looking at a small bill needs to know how
 * much of it was free, and one looking at a large bill needs to know the free
 * part has run out.
 */
export function MetricCostTable({
  rows,
  format,
  emptyLabel,
  ariaLabel,
  dense = false,
}: {
  rows: MetricCost[]
  format: CurrencyFormat
  emptyLabel: string
  /** Required, and distinct per instance: the page renders this table twice
   * (today, and the period), and two tables sharing one accessible name give
   * a screen-reader user no way to tell which is which. */
  ariaLabel: string
  dense?: boolean
}) {
  const { t, i18n } = useTranslation('billing')

  if (rows.length === 0) {
    return (
      <Typography variant="body2" color="text.secondary" sx={{ py: 2 }}>
        {emptyLabel}
      </Typography>
    )
  }

  return (
    <Box sx={{ overflowX: 'auto' }}>
      <Table size={dense ? 'small' : 'medium'} aria-label={ariaLabel}>
        <TableHead>
          <TableRow>
            <TableCell>{t('usage.metric')}</TableCell>
            <TableCell align="right">{t('usage.quantity')}</TableCell>
            <TableCell align="right">{t('usage.included')}</TableCell>
            <TableCell align="right">{t('usage.billable')}</TableCell>
            <TableCell align="right">{t('usage.unitPrice')}</TableCell>
            <TableCell align="right">{t('usage.estimatedCost')}</TableCell>
            {dense ? null : <TableCell sx={{ width: 140 }}>{t('usage.share')}</TableCell>}
          </TableRow>
        </TableHead>
        <TableBody>
          {rows.map((row) => (
            <TableRow key={row.metric_code} hover>
              <TableCell>
                <Stack>
                  {/* The server sends the name it snapshotted, so a metric
                      renamed later cannot relabel history. Translated from the
                      code where this build knows it, so an Arabic customer is
                      not reading English product nouns in their own table. */}
                  <Typography variant="body2">
                    {t(`metric.${row.metric_code}`, { defaultValue: row.display_name })}
                  </Typography>
                  <Typography variant="caption" color="text.secondary">
                    {t(`unit.${row.unit}`, { defaultValue: row.unit })}
                  </Typography>
                </Stack>
              </TableCell>
              <TableCell align="right" sx={{ fontVariantNumeric: 'tabular-nums' }}>
                {formatQuantity(row.quantity, i18n.language)}
              </TableCell>
              <TableCell align="right" sx={{ fontVariantNumeric: 'tabular-nums' }}>
                {formatQuantity(row.included_quantity, i18n.language)}
              </TableCell>
              <TableCell align="right" sx={{ fontVariantNumeric: 'tabular-nums' }}>
                {formatQuantity(row.billable_quantity, i18n.language)}
              </TableCell>
              <TableCell align="right" sx={{ fontVariantNumeric: 'tabular-nums' }}>
                {row.unit_amount === null ? (
                  // A metric with no configured price. Shown as a gap rather
                  // than as free, which it is not.
                  <Typography variant="caption" color="warning.main">
                    {t('usage.unpriced')}
                  </Typography>
                ) : (
                  formatUnitPrice(row.unit_amount, format, i18n.language)
                )}
              </TableCell>
              <TableCell align="right" sx={{ fontVariantNumeric: 'tabular-nums' }}>
                {formatEstimate(row.estimated_cost, format, i18n.language)}
              </TableCell>
              {dense ? null : (
                <TableCell>
                  <Stack spacing={0.5}>
                    <LinearProgress
                      variant="determinate"
                      // Clamped, not trusted: a share above 100 would render
                      // as a bar past its own track.
                      value={Math.min(100, Math.max(0, Number(row.share_percent) || 0))}
                      aria-label={t('usage.shareAriaLabel', {
                        metric: t(`metric.${row.metric_code}`, {
                          defaultValue: row.display_name,
                        }),
                      })}
                    />
                    <Typography variant="caption" color="text.secondary">
                      {formatPercent(row.share_percent, i18n.language)}
                    </Typography>
                  </Stack>
                </TableCell>
              )}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Box>
  )
}

import {
  Box,
  Card,
  CardContent,
  Chip,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Typography,
} from '@mui/material'
import { useTranslation } from 'react-i18next'
import { formatDay, formatQuantity, formatUnitPrice, type CurrencyFormat } from './money'
import type { UnitPrice } from './types'

/**
 * The rates this company is on, resolved by the Pricing Resolver.
 *
 * Not restated from anywhere: the resolver is the only thing that knows
 * whether a company has a negotiated override, sits on a pricing profile, or
 * takes the global rate — and the source is shown, because a customer on a
 * negotiated price should be able to see that it is being applied.
 */
export function CostTransparencyCard({
  prices,
  format,
}: {
  prices: UnitPrice[]
  format: CurrencyFormat
}) {
  const { t, i18n } = useTranslation('billing')

  return (
    <Card variant="outlined">
      <CardContent>
        <Stack spacing={0.5} sx={{ mb: 2 }}>
          <Typography variant="subtitle1" component="h2" sx={{ fontWeight: 600 }}>
            {t('prices.title')}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            {t('prices.subtitle')}
          </Typography>
        </Stack>
        <Box sx={{ overflowX: 'auto' }}>
          <Table size="small" aria-label={t('prices.tableAriaLabel')}>
            <TableHead>
              <TableRow>
                <TableCell>{t('usage.metric')}</TableCell>
                <TableCell align="right">{t('usage.unitPrice')}</TableCell>
                <TableCell align="right">{t('prices.allowance')}</TableCell>
                <TableCell>{t('prices.source')}</TableCell>
                <TableCell>{t('prices.effectiveFrom')}</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {prices.map((price) => (
                <TableRow key={price.metric_code} hover>
                  <TableCell>
                    <Stack>
                      <Typography variant="body2">
                        {t(`metric.${price.metric_code}`, { defaultValue: price.display_name })}
                      </Typography>
                      <Typography variant="caption" color="text.secondary">
                        {t('prices.perUnit', {
                          unit: t(`unit.${price.unit}`, { defaultValue: price.unit }),
                        })}
                      </Typography>
                    </Stack>
                  </TableCell>
                  <TableCell align="right" sx={{ fontVariantNumeric: 'tabular-nums' }}>
                    {price.unit_amount === null ? (
                      <Typography variant="caption" color="text.secondary">
                        {t('prices.notPriced')}
                      </Typography>
                    ) : (
                      formatUnitPrice(
                        price.unit_amount,
                        { currency: price.currency || format.currency, decimals: format.decimals },
                        i18n.language,
                      )
                    )}
                  </TableCell>
                  <TableCell align="right" sx={{ fontVariantNumeric: 'tabular-nums' }}>
                    {Number(price.free_allowance) > 0
                      ? formatQuantity(price.free_allowance, i18n.language)
                      : '—'}
                  </TableCell>
                  <TableCell>
                    {price.source ? (
                      <Chip
                        size="small"
                        variant={price.source === 'company' ? 'filled' : 'outlined'}
                        color={price.source === 'company' ? 'primary' : 'default'}
                        label={t(`prices.sourceLabel.${price.source}`)}
                      />
                    ) : (
                      '—'
                    )}
                  </TableCell>
                  <TableCell>
                    {price.effective_from
                      ? formatDay(price.effective_from.slice(0, 10), i18n.language)
                      : '—'}
                    {price.tiers.length > 0 ? (
                      // The table behind a volume rate. Without it, "why am I
                      // paying 0.002?" has no answer on the page.
                      <Stack sx={{ mt: 0.5 }}>
                        {price.tiers.map((tier) => (
                          <Typography
                            key={tier.up_to ?? 'above'}
                            variant="caption"
                            color="text.secondary"
                          >
                            {tier.up_to === null
                              ? t('prices.tierAbove', {
                                  amount: formatUnitPrice(
                                    tier.unit_amount,
                                    {
                                      currency: price.currency || format.currency,
                                      decimals: format.decimals,
                                    },
                                    i18n.language,
                                  ),
                                })
                              : t('prices.tierUpTo', {
                                  quantity: formatQuantity(tier.up_to, i18n.language),
                                  amount: formatUnitPrice(
                                    tier.unit_amount,
                                    {
                                      currency: price.currency || format.currency,
                                      decimals: format.decimals,
                                    },
                                    i18n.language,
                                  ),
                                })}
                          </Typography>
                        ))}
                      </Stack>
                    ) : null}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Box>
      </CardContent>
    </Card>
  )
}

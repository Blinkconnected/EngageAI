import { Box, Card, CardContent, LinearProgress, Stack, Tab, Tabs, Typography } from '@mui/material'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { formatQuantity } from './money'
import type { MessageBreakdown } from './types'

/**
 * Where this period's messages came from — by channel, by who sent them, by
 * direction.
 *
 * **Counts, never money.** Billing is channel-agnostic: a message costs the
 * same on WhatsApp as on web chat, so a per-channel cost would be a number the
 * invoice does not contain. What a company actually wants here is volume —
 * "where is our traffic?" and "how much is the AI doing?" — and the rate card
 * already says what a message costs.
 */
export function MessageMixCard({ breakdowns }: { breakdowns: MessageBreakdown[] }) {
  const { t, i18n } = useTranslation('billing')
  const [selected, setSelected] = useState(0)

  if (breakdowns.length === 0) return null

  const active = breakdowns[Math.min(selected, breakdowns.length - 1)]

  return (
    <Card variant="outlined" sx={{ height: '100%' }} data-testid="message-mix">
      <CardContent>
        <Stack spacing={0.5}>
          <Typography variant="subtitle1" component="h2" sx={{ fontWeight: 600 }}>
            {t('mix.title')}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            {t('mix.subtitle')}
          </Typography>
        </Stack>

        <Tabs
          value={Math.min(selected, breakdowns.length - 1)}
          onChange={(_event, next: number) => setSelected(next)}
          sx={{ mb: 1, minHeight: 40 }}
          aria-label={t('mix.tabsAriaLabel')}
        >
          {breakdowns.map((breakdown) => (
            <Tab
              key={breakdown.dimension}
              label={t(`mix.dimension.${breakdown.dimension}`, {
                defaultValue: breakdown.dimension,
              })}
              sx={{ minHeight: 40 }}
            />
          ))}
        </Tabs>

        <Stack spacing={1.5}>
          {active.rows.map(([label, count]) => (
            <Box key={label}>
              <Stack direction="row" sx={{ justifyContent: 'space-between', mb: 0.25 }}>
                <Typography variant="body2">
                  {t(`mix.label.${label}`, { defaultValue: label })}
                </Typography>
                <Typography variant="body2" sx={{ fontVariantNumeric: 'tabular-nums' }}>
                  {formatQuantity(String(count), i18n.language)}
                </Typography>
              </Stack>
              <LinearProgress
                variant="determinate"
                // Share of the dimension's own total, so the bars fill the row
                // rather than all looking tiny next to an outlier.
                value={active.total > 0 ? Math.min(100, (count / active.total) * 100) : 0}
                aria-label={t('mix.shareAriaLabel', {
                  label: t(`mix.label.${label}`, { defaultValue: label }),
                })}
              />
            </Box>
          ))}
        </Stack>

        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 2 }}>
          {t('mix.total', { count: formatQuantity(String(active.total), i18n.language) })}
        </Typography>
      </CardContent>
    </Card>
  )
}

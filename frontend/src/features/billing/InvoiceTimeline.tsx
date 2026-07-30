import {
  Box,
  Card,
  CardContent,
  Stack,
  Step,
  StepContent,
  StepLabel,
  Stepper,
  Typography,
} from '@mui/material'
import { useTranslation } from 'react-i18next'
import { formatDay } from './money'
import type { TimelineEvent } from './types'

/**
 * Usage -> close -> invoice -> due -> suspension, with today's position marked.
 *
 * The suspension step is shown before anything has gone wrong on purpose. It
 * is the most consequential date in billing and the hardest to work out from
 * a list of reminder rules, and the worst way to learn it is by being
 * suspended.
 */
export function InvoiceTimeline({
  events,
  paymentTermsDays,
  suspendAfterDays,
}: {
  events: TimelineEvent[]
  /** The two numbers the step descriptions quote. Passed in from the billing
   * configuration rather than hardcoded, so the timeline cannot promise
   * different terms from the rest of the page. */
  paymentTermsDays: number
  suspendAfterDays: number | null
}) {
  const { t, i18n } = useTranslation('billing')
  const activeIndex = Math.max(
    0,
    events.findIndex((event) => event.state === 'current'),
  )

  return (
    <Card variant="outlined" sx={{ height: '100%' }}>
      <CardContent>
        <Typography variant="subtitle1" component="h2" sx={{ fontWeight: 600, mb: 2 }}>
          {t('timeline.title')}
        </Typography>
        {events.length === 0 ? (
          <Typography variant="body2" color="text.secondary">
            {t('timeline.empty')}
          </Typography>
        ) : (
          <Stepper activeStep={activeIndex} orientation="vertical" nonLinear>
            {events.map((event) => (
              <Step key={event.key} completed={event.state === 'done'} expanded>
                <StepLabel>
                  <Stack
                    direction={{ xs: 'column', sm: 'row' }}
                    spacing={{ xs: 0, sm: 1 }}
                    sx={{ alignItems: { sm: 'baseline' } }}
                  >
                    <Typography variant="body2" sx={{ fontWeight: 500 }}>
                      {/* Translated from the step's stable key, with the
                          server's English label as the fallback — the same
                          rule as the status sentence: composed once
                          server-side, read in the customer's language. */}
                      {t(`timeline.event.${event.key}`, { defaultValue: event.label })}
                    </Typography>
                    <Box
                      component="time"
                      dateTime={event.at}
                      sx={{ color: 'text.secondary', fontSize: 13 }}
                    >
                      {formatDay(event.at, i18n.language)}
                    </Box>
                  </Stack>
                </StepLabel>
                {event.detail ? (
                  <StepContent>
                    <Typography variant="caption" color="text.secondary">
                      {t(`timeline.detail.${event.key}`, {
                        terms: paymentTermsDays,
                        suspendAfter: suspendAfterDays ?? 0,
                        defaultValue: event.detail,
                      })}
                    </Typography>
                  </StepContent>
                ) : null}
              </Step>
            ))}
          </Stepper>
        )}
      </CardContent>
    </Card>
  )
}

import { memo, type ReactNode } from 'react'
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Box,
  Chip,
  Divider,
  Stack,
  Typography,
} from '@mui/material'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import { useTranslation } from 'react-i18next'
import type { ConversationInspection } from './types'

/** Seconds as a person would say them.
 *
 * Formatted here rather than on the server: "4m 12s" in English is not
 * "4د 12ث" in Arabic, and the server has no business deciding which one the
 * reader gets. The API sends numbers.
 */
function duration(seconds: number | null): string {
  if (seconds === null || Number.isNaN(seconds)) return '—'
  const total = Math.max(0, Math.round(seconds))
  if (total < 60) return `${total}s`
  const minutes = Math.floor(total / 60)
  if (minutes < 60) return `${minutes}m ${total % 60}s`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ${minutes % 60}m`
  return `${Math.floor(hours / 24)}d ${hours % 24}h`
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <Box sx={{ minWidth: 0 }}>
      <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
        {label}
      </Typography>
      <Typography variant="body2" sx={{ fontWeight: 500, wordBreak: 'break-word' }}>
        {children}
      </Typography>
    </Box>
  )
}

/** The operational card. Nothing technical, deliberately: this answers "what
 * is going on with this customer", and an id answers nothing a manager
 * asked. Identifiers live in the Technical card. */
export const SummaryCard = memo(function SummaryCard({
  inspection,
}: {
  inspection: ConversationInspection
}) {
  const { t } = useTranslation('inspector')
  const { summary } = inspection

  return (
    <Box
      sx={{
        p: 2,
        borderRadius: 1,
        border: 1,
        borderColor: 'divider',
        bgcolor: 'background.paper',
      }}
    >
      <Box
        sx={{
          display: 'grid',
          gap: 2,
          gridTemplateColumns: {
            xs: 'repeat(2, minmax(0, 1fr))',
            md: 'repeat(4, minmax(0, 1fr))',
          },
        }}
      >
        <Field label={t('summary.status')}>{summary.status.replace(/_/g, ' ')}</Field>
        <Field label={t('summary.owner')}>{summary.owner_label}</Field>
        <Field label={t('summary.customer')}>{summary.customer_name ?? '—'}</Field>
        <Field label={t('summary.agent')}>{summary.assigned_agent_name ?? '—'}</Field>
        <Field label={t('summary.service')}>{summary.service_name ?? t('summary.noService')}</Field>
        <Field label={t('summary.queue')}>{summary.queue_name ?? '—'}</Field>
        <Field label={t('summary.slaHealth')}>
          <Chip size="small" label={t(`health.${summary.sla_health}`)} sx={{ height: 20 }} />
        </Field>
        <Field label={t('summary.age')}>{duration(summary.age_seconds)}</Field>
      </Box>
    </Box>
  )
})

function Card({ title, count, children }: { title: string; count?: number; children: ReactNode }) {
  return (
    <Accordion disableGutters elevation={0} sx={{ border: 1, borderColor: 'divider' }}>
      <AccordionSummary expandIcon={<ExpandMoreIcon />}>
        <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
          <Typography variant="body2" sx={{ fontWeight: 600 }}>
            {title}
          </Typography>
          {count !== undefined ? (
            <Chip size="small" variant="outlined" label={count} sx={{ height: 18 }} />
          ) : null}
        </Stack>
      </AccordionSummary>
      <AccordionDetails>{children}</AccordionDetails>
    </Accordion>
  )
}

/** The supporting cards, collapsed by default.
 *
 * The timeline is the product; these exist for the reader who has found the
 * moment they care about and wants the same facts grouped by subject rather
 * than by time. Collapsed so they support the story instead of competing
 * with it.
 */
export const InspectorCards = memo(function InspectorCards({
  inspection,
}: {
  inspection: ConversationInspection
}) {
  const { t } = useTranslation('inspector')
  const { ownership, clocks, ai, policies, technical } = inspection

  return (
    <Stack spacing={1}>
      <Card title={t('cards.ownership')} count={ownership.length}>
        <Stack spacing={1.5} divider={<Divider flexItem />}>
          {ownership.length === 0 ? (
            <Typography variant="body2" color="text.secondary">
              {t('cards.nothingRecorded')}
            </Typography>
          ) : (
            ownership.map((span) => (
              <Box key={`${span.at}-${span.owner_label}`}>
                <Typography variant="body2" sx={{ fontWeight: 500 }}>
                  {span.previous_label ? `${span.previous_label} → ` : ''}
                  {span.owner_label}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  {span.reason_text} · {t('cards.held', { duration: duration(span.held_seconds) })}{' '}
                  · {span.responsibility.replace(/_/g, ' ')}
                </Typography>
                {span.note ? (
                  <Typography variant="caption" sx={{ display: 'block' }}>
                    {span.note}
                  </Typography>
                ) : null}
              </Box>
            ))
          )}
        </Stack>
      </Card>

      <Card title={t('cards.sla')} count={clocks.length}>
        <Stack spacing={1.5} divider={<Divider flexItem />}>
          {clocks.length === 0 ? (
            <Typography variant="body2" color="text.secondary">
              {t('cards.noClocks')}
            </Typography>
          ) : (
            clocks.map((clock) => (
              <Box key={clock.timer}>
                {/* The question the clock answers, not its column name: a
                    timer labelled "first_response" explains nothing to
                    somebody asking why a conversation is red. */}
                <Typography variant="body2" sx={{ fontWeight: 500 }}>
                  {clock.question}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  {t(`clockState.${clock.state}`, { defaultValue: clock.state })} ·{' '}
                  {t('cards.counted', { duration: duration(clock.counted_seconds) })}
                  {clock.target_minutes !== null
                    ? ` · ${t('cards.target', { minutes: clock.target_minutes })}`
                    : ''}
                </Typography>
                <Typography variant="caption" sx={{ display: 'block' }}>
                  {t('cards.waitingOn', { who: clock.responsible })}
                </Typography>
                {clock.pause_text ? (
                  <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
                    {clock.pause_text}
                    {clock.pause_note ? ` — ${clock.pause_note}` : ''}
                  </Typography>
                ) : null}
              </Box>
            ))
          )}
        </Stack>
      </Card>

      <Card title={t('cards.ai')}>
        <Box
          sx={{
            display: 'grid',
            gap: 1.5,
            gridTemplateColumns: { xs: '1fr', sm: 'repeat(2, minmax(0, 1fr))' },
          }}
        >
          <Field label={t('ai.state')}>
            {t(`aiState.${ai.state}`, { defaultValue: ai.state.replace(/_/g, ' ') })}
          </Field>
          <Field label={t('ai.pickupDelay')}>
            {ai.pickup_delay_seconds === null ? '—' : `${ai.pickup_delay_seconds}s`}
          </Field>
          <Field label={t('ai.threshold')}>{ai.confidence_threshold ?? '—'}</Field>
          <Field label={t('ai.thresholdSource')}>
            {ai.threshold_source
              ? t(`ai.source.${ai.threshold_source}`, { defaultValue: ai.threshold_source })
              : '—'}
          </Field>
          <Field label={t('ai.resumeEligible')}>{ai.resume_eligible ? t('yes') : t('no')}</Field>
          <Field label={t('ai.blocked')}>{ai.resume_blocked_because ?? '—'}</Field>
        </Box>
        {ai.reasons.length > 0 ? (
          <Stack component="ul" spacing={0.25} sx={{ mt: 2, pl: 2.5 }}>
            {ai.reasons.map((reason) => (
              <Typography key={reason} component="li" variant="body2" color="text.secondary">
                {reason}
              </Typography>
            ))}
          </Stack>
        ) : null}
      </Card>

      <Card title={t('cards.policies')} count={policies.length}>
        <Stack spacing={1}>
          {policies.length === 0 ? (
            <Typography variant="body2" color="text.secondary">
              {t('cards.nothingRecorded')}
            </Typography>
          ) : (
            policies.map((policy) => (
              <Box key={`${policy.at}-${policy.policy}-${policy.reason}`}>
                <Typography variant="body2">{policy.sentence}</Typography>
                <Typography variant="caption" color="text.secondary">
                  {policy.policy.replace(/_/g, ' ')} · {policy.effect} ·{' '}
                  {policy.source.replace(/_/g, ' ')}
                </Typography>
              </Box>
            ))
          )}
        </Stack>
      </Card>

      <Card title={t('cards.technical')}>
        <Box
          sx={{
            display: 'grid',
            gap: 1.5,
            gridTemplateColumns: { xs: '1fr', sm: 'repeat(2, minmax(0, 1fr))' },
          }}
        >
          <Field label={t('technical.conversationId')}>{technical.conversation_id}</Field>
          <Field label={t('technical.customerId')}>{technical.customer_id ?? '—'}</Field>
          <Field label={t('technical.serviceVersionId')}>
            {technical.service_version_id ?? '—'}
          </Field>
          <Field label={t('technical.serviceVersion')}>{technical.service_version ?? '—'}</Field>
          <Field label={t('technical.customerContextVersionId')}>
            {technical.customer_context_version_id ?? '—'}
          </Field>
          <Field label={t('technical.boundAt')}>{technical.context_bound_at ?? '—'}</Field>
        </Box>
        {technical.unversioned.length > 0 ? (
          <Box sx={{ mt: 2 }}>
            {/* Said out loud so an engineer stops looking for a version that
                was never minted. */}
            <Typography variant="caption" color="text.secondary">
              {t('technical.unversioned')}
            </Typography>
            <Stack direction="row" spacing={0.5} sx={{ mt: 0.5, flexWrap: 'wrap', gap: 0.5 }}>
              {technical.unversioned.map((name) => (
                <Chip key={name} size="small" variant="outlined" label={name} />
              ))}
            </Stack>
          </Box>
        ) : null}
      </Card>
    </Stack>
  )
})

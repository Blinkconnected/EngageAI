import { Chip, Tooltip } from '@mui/material'
import { useTranslation } from 'react-i18next'
import type { ChannelConfig } from './types'

/** O(1) glance at whether a channel is currently reachable — backed by
 * `ChannelConfig.last_health_status`, kept fresh by the "Test Connection"
 * button and the periodic health-monitoring sweep (both write the same
 * columns). See channel-integration-spec.md. */
export function ChannelHealthBadge({ channel }: { channel: ChannelConfig }) {
  const { t } = useTranslation('channelsCore')

  if (channel.last_health_status == null) {
    return (
      <Chip size="small" label={t('ChannelHealthBadge.notTestedYetLabel')} variant="outlined" />
    )
  }

  const healthy = channel.last_health_status === 'healthy'
  const checkedAt = channel.last_health_checked_at
    ? new Date(channel.last_health_checked_at).toLocaleString()
    : null
  const healthyLabel = healthy
    ? t('ChannelHealthBadge.healthyLabel')
    : t('ChannelHealthBadge.unhealthyLabel')
  // "provider"/"network" means the provider's own servers aren't
  // responding (not us); "configuration" means our credentials/setup are
  // wrong (ours to fix); "internal" (Web Chat only) means our own
  // storage. Shown alongside the raw detail, not instead of it — the
  // classification says *whose* problem it is, the detail says *what*
  // happened.
  const originLabel =
    !healthy && channel.last_health_origin
      ? t(`ChannelHealthBadge.origin.${channel.last_health_origin}`)
      : null
  const tooltip = [
    originLabel,
    channel.last_health_detail,
    checkedAt ? t('ChannelHealthBadge.checkedAtLabel', { checkedAt }) : null,
  ]
    .filter(Boolean)
    .join(' — ')

  return (
    <Tooltip title={tooltip || healthyLabel}>
      <Chip size="small" label={healthyLabel} color={healthy ? 'success' : 'error'} />
    </Tooltip>
  )
}

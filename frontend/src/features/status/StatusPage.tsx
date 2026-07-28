import { useMemo, useState, type ComponentType } from 'react'
import {
  Alert,
  Button,
  Card,
  CardContent,
  Chip,
  Divider,
  Grid,
  Stack,
  Typography,
} from '@mui/material'
import { useTranslation } from 'react-i18next'
import RefreshOutlinedIcon from '@mui/icons-material/RefreshOutlined'
import WhatsAppIcon from '@mui/icons-material/WhatsApp'
import TelegramIcon from '@mui/icons-material/Telegram'
import FacebookIcon from '@mui/icons-material/Facebook'
import InstagramIcon from '@mui/icons-material/Instagram'
import EmailOutlinedIcon from '@mui/icons-material/EmailOutlined'
import SmsOutlinedIcon from '@mui/icons-material/SmsOutlined'
import ChatBubbleOutlineOutlinedIcon from '@mui/icons-material/ChatBubbleOutlineOutlined'
import HubOutlinedIcon from '@mui/icons-material/HubOutlined'
import { PageHeader } from '../../shared/components/PageHeader'
import { LoadingState } from '../../shared/components/LoadingState'
import { ErrorState } from '../../shared/components/ErrorState'
import { usePermissions } from '../../shared/hooks/usePermissions'
import { ChannelHealthBadge } from '../channels/ChannelHealthBadge'
import { TestConnectionButton } from '../channels/TestConnectionButton'
import { useAllChannelsQuery, useTestConnectionMutation } from '../channels/api'
import {
  CHANNEL_TYPES,
  channelTypeLabel,
  type ChannelConfig,
  type HealthCheckOrigin,
} from '../channels/types'

type IconType = ComponentType<{ fontSize?: 'small' | 'medium' | 'large' | 'inherit' }>

/** Falls back to a generic hub icon for any channel type not listed here —
 * e.g. a brand-new provider added to `CHANNEL_TYPES` before this map is
 * updated, keeping this page working for a type it doesn't have a
 * dedicated icon for yet rather than crashing. */
const CHANNEL_TYPE_ICONS: Record<string, IconType> = {
  whatsapp: WhatsAppIcon,
  telegram: TelegramIcon,
  messenger: FacebookIcon,
  instagram: InstagramIcon,
  email: EmailOutlinedIcon,
  sms: SmsOutlinedIcon,
  web_chat: ChatBubbleOutlineOutlinedIcon,
}

type AggregateStatus = 'operational' | 'degraded' | 'not_tested' | 'inactive' | 'not_configured'

const STATUS_COLOR: Record<AggregateStatus, 'success' | 'error' | 'default'> = {
  operational: 'success',
  degraded: 'error',
  not_tested: 'default',
  inactive: 'default',
  not_configured: 'default',
}

/** One channel type's status is derived entirely from
 * `ChannelConfig.last_health_status`/`is_active` — the same fields
 * `ChannelHealthBadge` already reads per config, kept fresh by the
 * existing "Test Connection" action and the periodic health-check sweep
 * (see docs/architecture/channels.md). A type can have zero, one, or
 * several configs (e.g. two WhatsApp numbers); any unhealthy *active*
 * config marks the whole type degraded, even if a sibling config of the
 * same type is fine. */
function aggregateStatus(configs: ChannelConfig[]): AggregateStatus {
  if (configs.length === 0) return 'not_configured'
  const active = configs.filter((channel) => channel.is_active)
  if (active.length === 0) return 'inactive'
  if (active.some((channel) => channel.last_health_status === 'unhealthy')) return 'degraded'
  if (active.some((channel) => channel.last_health_status === 'healthy')) return 'operational'
  return 'not_tested'
}

/** Whose fault a degraded channel type is, for the whole card — not just
 * one config's tooltip. When active configs disagree (rare — usually one
 * shared API key), "configuration" wins: it's the most actionable
 * reading for an operator, mirroring EmailProvider's own SMTP-vs-IMAP
 * tie-break. Returns null unless the type is actually degraded. */
function dominantUnhealthyOrigin(configs: ChannelConfig[]): HealthCheckOrigin | null {
  const origins = configs
    .filter((channel) => channel.is_active && channel.last_health_status === 'unhealthy')
    .map((channel) => channel.last_health_origin)
    .filter((origin): origin is HealthCheckOrigin => origin != null)
  if (origins.length === 0) return null
  return origins.includes('configuration') ? 'configuration' : origins[0]
}

function groupByChannelType(channels: ChannelConfig[]): Map<string, ChannelConfig[]> {
  const grouped = new Map<string, ChannelConfig[]>()
  for (const type of CHANNEL_TYPES) grouped.set(type.value, [])
  for (const channel of channels) {
    const bucket = grouped.get(channel.channel_type)
    if (bucket) {
      bucket.push(channel)
    } else {
      // A channel type not yet in CHANNEL_TYPES (a brand-new provider) —
      // still gets its own card, not silently dropped.
      grouped.set(channel.channel_type, [channel])
    }
  }
  return grouped
}

function mostRecentCheck(configs: ChannelConfig[]): string | null {
  const timestamps = configs
    .map((channel) => channel.last_health_checked_at)
    .filter((value): value is string => value != null)
    .sort()
  return timestamps.at(-1) ?? null
}

export function StatusPage() {
  const { t, i18n } = useTranslation('status')
  const { hasPermission } = usePermissions()
  const canManage = hasPermission('channels.manage')

  const channelsQuery = useAllChannelsQuery()
  const testConnectionMutation = useTestConnectionMutation()
  const [checkingAll, setCheckingAll] = useState(false)
  const [checkAllError, setCheckAllError] = useState<string | null>(null)

  const grouped = useMemo(() => groupByChannelType(channelsQuery.data ?? []), [channelsQuery.data])

  const STATUS_LABEL: Record<AggregateStatus, string> = useMemo(
    () => ({
      operational: t('StatusPage.operationalStatus'),
      degraded: t('StatusPage.degradedStatus'),
      not_tested: t('StatusPage.notTestedStatus'),
      inactive: t('StatusPage.inactiveStatus'),
      not_configured: t('StatusPage.notConfiguredStatus'),
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [t, i18n.language],
  )

  async function handleCheckAll() {
    const channels = channelsQuery.data ?? []
    if (channels.length === 0) return
    setCheckingAll(true)
    setCheckAllError(null)
    const results = await Promise.allSettled(
      channels.map((channel) => testConnectionMutation.mutateAsync(channel.id)),
    )
    setCheckingAll(false)
    if (results.some((result) => result.status === 'rejected')) {
      setCheckAllError(t('StatusPage.checkAllErrorMessage'))
    }
  }

  return (
    <>
      <PageHeader
        title={t('StatusPage.pageTitle')}
        description={t('StatusPage.pageDescription')}
        actions={
          canManage && (
            <Button
              variant="outlined"
              startIcon={<RefreshOutlinedIcon />}
              onClick={handleCheckAll}
              disabled={checkingAll || (channelsQuery.data?.length ?? 0) === 0}
            >
              {checkingAll ? t('StatusPage.checkingButton') : t('StatusPage.checkAllButton')}
            </Button>
          )
        }
      />

      {checkAllError && (
        <Alert severity="warning" sx={{ mb: 2 }}>
          {checkAllError}
        </Alert>
      )}

      {channelsQuery.isPending && <LoadingState label={t('StatusPage.loadingLabel')} />}

      {channelsQuery.isError && (
        <ErrorState error={channelsQuery.error} onRetry={() => channelsQuery.refetch()} />
      )}

      {channelsQuery.data && (
        <Grid container spacing={2}>
          {Array.from(grouped.entries()).map(([channelType, configs]) => {
            const Icon = CHANNEL_TYPE_ICONS[channelType] ?? HubOutlinedIcon
            const status = aggregateStatus(configs)
            const meta = { label: STATUS_LABEL[status], color: STATUS_COLOR[status] }
            const lastChecked = mostRecentCheck(configs)
            const label = channelTypeLabel(channelType)
            const origin = status === 'degraded' ? dominantUnhealthyOrigin(configs) : null

            return (
              <Grid key={channelType} size={{ xs: 12, md: 6 }}>
                <Card variant="outlined">
                  <CardContent>
                    <Stack direction="row" spacing={1} sx={{ alignItems: 'center', mb: 1.5 }}>
                      <Icon fontSize="small" />
                      {/* `component="h2"` — directly under PageHeader's own
                          `h1`, same heading-order rationale as
                          DashboardPage's StatCard (the default h4 this
                          variant would render as skips two levels). */}
                      <Typography
                        variant="subtitle1"
                        component="h2"
                        sx={{ fontWeight: 600, flexGrow: 1 }}
                      >
                        {label}
                      </Typography>
                      <Chip
                        label={meta.label}
                        size="small"
                        color={meta.color}
                        data-testid="channel-type-status"
                      />
                    </Stack>

                    {origin && (
                      // The one line that answers "is this our problem or
                      // theirs?" — a provider/network origin means the
                      // provider's own infrastructure is down, not
                      // BlinkEngage; configuration/internal both mean
                      // ours to fix.
                      <Alert
                        severity={
                          origin === 'configuration' || origin === 'internal' ? 'warning' : 'error'
                        }
                        sx={{ mb: 1.5 }}
                        data-testid="channel-type-origin"
                      >
                        {t(`StatusPage.origin.${origin}`, { label })}
                      </Alert>
                    )}

                    {configs.length === 0 ? (
                      <Typography variant="body2" color="text.secondary">
                        {t('StatusPage.noChannelConnectedMessage', { label })}
                      </Typography>
                    ) : (
                      <Stack spacing={1.5} divider={<Divider flexItem />}>
                        {configs.map((channel) => (
                          <Stack key={channel.id} spacing={0.75}>
                            <Stack
                              direction="row"
                              spacing={1}
                              sx={{ alignItems: 'center', justifyContent: 'space-between' }}
                            >
                              <Typography variant="body2">{channel.display_name}</Typography>
                              <ChannelHealthBadge channel={channel} />
                            </Stack>
                            {canManage && (
                              <TestConnectionButton
                                onTest={() => testConnectionMutation.mutateAsync(channel.id)}
                              />
                            )}
                          </Stack>
                        ))}
                      </Stack>
                    )}

                    {lastChecked && (
                      <Typography
                        variant="caption"
                        color="text.secondary"
                        sx={{ display: 'block', mt: 1.5 }}
                      >
                        {t('StatusPage.lastCheckedMessage', {
                          date: new Date(lastChecked).toLocaleString(),
                        })}
                      </Typography>
                    )}
                  </CardContent>
                </Card>
              </Grid>
            )
          })}
        </Grid>
      )}
    </>
  )
}

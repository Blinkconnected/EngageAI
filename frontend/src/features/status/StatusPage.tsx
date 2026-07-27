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
import { CHANNEL_TYPES, channelTypeLabel, type ChannelConfig } from '../channels/types'

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

const STATUS_META: Record<
  AggregateStatus,
  { label: string; color: 'success' | 'error' | 'default' }
> = {
  operational: { label: 'Operational', color: 'success' },
  degraded: { label: 'Degraded', color: 'error' },
  not_tested: { label: 'Not tested yet', color: 'default' },
  inactive: { label: 'Inactive', color: 'default' },
  not_configured: { label: 'Not configured', color: 'default' },
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
  const { hasPermission } = usePermissions()
  const canManage = hasPermission('channels.manage')

  const channelsQuery = useAllChannelsQuery()
  const testConnectionMutation = useTestConnectionMutation()
  const [checkingAll, setCheckingAll] = useState(false)
  const [checkAllError, setCheckAllError] = useState<string | null>(null)

  const grouped = useMemo(
    () => groupByChannelType(channelsQuery.data ?? []),
    [channelsQuery.data],
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
      setCheckAllError(
        'Some channels could not be checked just now — see their individual status below.',
      )
    }
  }

  return (
    <>
      <PageHeader
        title="Provider & Service Status"
        description="Live connectivity status for every messaging channel your company uses."
        actions={
          canManage && (
            <Button
              variant="outlined"
              startIcon={<RefreshOutlinedIcon />}
              onClick={handleCheckAll}
              disabled={checkingAll || (channelsQuery.data?.length ?? 0) === 0}
            >
              {checkingAll ? 'Checking…' : 'Check all now'}
            </Button>
          )
        }
      />

      {checkAllError && (
        <Alert severity="warning" sx={{ mb: 2 }}>
          {checkAllError}
        </Alert>
      )}

      {channelsQuery.isPending && <LoadingState label="Loading provider status…" />}

      {channelsQuery.isError && (
        <ErrorState error={channelsQuery.error} onRetry={() => channelsQuery.refetch()} />
      )}

      {channelsQuery.data && (
        <Grid container spacing={2}>
          {Array.from(grouped.entries()).map(([channelType, configs]) => {
            const Icon = CHANNEL_TYPE_ICONS[channelType] ?? HubOutlinedIcon
            const status = aggregateStatus(configs)
            const meta = STATUS_META[status]
            const lastChecked = mostRecentCheck(configs)
            const label = channelTypeLabel(channelType)

            return (
              <Grid key={channelType} size={{ xs: 12, md: 6 }}>
                <Card variant="outlined">
                  <CardContent>
                    <Stack
                      direction="row"
                      spacing={1}
                      sx={{ alignItems: 'center', mb: 1.5 }}
                    >
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

                    {configs.length === 0 ? (
                      <Typography variant="body2" color="text.secondary">
                        No {label} channel connected yet.
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
                        Last checked {new Date(lastChecked).toLocaleString()}
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

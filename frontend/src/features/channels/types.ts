/** Matches the backend's `ChannelConfigResponse` — credentials and
 * webhook_secret are deliberately never echoed back once stored. */
export interface ChannelConfig {
  id: string
  channel_type: string
  display_name: string
  is_active: boolean
  last_health_status: 'healthy' | 'unhealthy' | null
  last_health_checked_at: string | null
  last_health_detail: string | null
  created_at: string
  updated_at: string
}

/** Matches the backend's `ChannelConfigCreateResponse` — returned only
 * from `POST /channel-configs`, the one moment a server-auto-generated
 * `webhook_secret` (and, for WhatsApp, `verify_token`) needs to leave the
 * server at all, so the operator can paste it into the provider's own
 * dashboard. Every other response uses the base `ChannelConfig`. */
export interface ChannelConfigCreateResult extends ChannelConfig {
  webhook_secret: string
  verify_token: string | null
}

export interface ChannelConfigCreateRequest {
  channel_type: string
  display_name: string
  credentials: Record<string, unknown>
  webhook_secret?: string | null
}

export interface ChannelConfigUpdateRequest {
  display_name?: string
  credentials?: Record<string, unknown>
  webhook_secret?: string | null
  is_active?: boolean
}

export interface TestConnectionRequest {
  channel_type: string
  credentials: Record<string, unknown>
  webhook_secret?: string | null
}

/** Matches the backend's `TestConnectionResponse`. */
export interface TestConnectionResult {
  healthy: boolean
  detail: string | null
}

/** Matches the backend's `ChannelConnectionLogResponse`. */
export interface ChannelConnectionLog {
  id: string
  event_type: string
  level: 'info' | 'warning' | 'error'
  message: string
  log_metadata: Record<string, unknown>
  created_at: string
}

/** The fixed set of channel types this backend's `ChannelRegistry` has a
 * provider registered for — see infrastructure/channels/providers/. */
export const CHANNEL_TYPES = [
  { value: 'whatsapp', label: 'WhatsApp Business' },
  { value: 'telegram', label: 'Telegram' },
  { value: 'messenger', label: 'Facebook Messenger' },
  { value: 'instagram', label: 'Instagram' },
  { value: 'email', label: 'Email' },
  { value: 'sms', label: 'SMS' },
  { value: 'web_chat', label: 'Web Chat' },
] as const

/** Channels with a guided, per-field setup wizard (Phase 1: Channel
 * Experience). Every other type still falls back to the generic JSON
 * credentials textarea — see channel-integration-spec.md's "priority
 * order" scoping. */
export const GUIDED_CHANNEL_TYPES = ['whatsapp', 'telegram', 'email', 'web_chat'] as const

export function channelTypeLabel(channelType: string): string {
  return CHANNEL_TYPES.find((type) => type.value === channelType)?.label ?? channelType
}

export function hasGuidedSetup(channelType: string): boolean {
  return (GUIDED_CHANNEL_TYPES as readonly string[]).includes(channelType)
}

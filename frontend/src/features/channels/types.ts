/** Whose fault an unhealthy check is — matches the backend's
 * `domain.channels.HealthCheckOrigin`. `null` when healthy or not yet
 * checked. Lets the Status page say more than a flat red chip: a
 * "provider"/"network" failure means the provider's own infrastructure
 * is down (not us), "configuration" means our credentials/setup are
 * wrong (ours to fix), and "internal" (Web Chat only, which has no
 * third-party upstream) means our own MinIO attachment store. */
export type HealthCheckOrigin = 'provider' | 'configuration' | 'network' | 'internal'

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
  last_health_origin: HealthCheckOrigin | null
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
  origin: HealthCheckOrigin | null
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
export const GUIDED_CHANNEL_TYPES = [
  'whatsapp',
  'messenger',
  'instagram',
  'telegram',
  'email',
  'web_chat',
] as const

/** Channels whose webhook secret is **the provider's own signing
 * secret**, not a value this system invents.
 *
 * Meta signs every webhook delivery with the App Secret from the app
 * dashboard. Generating a random one produces the worst failure this
 * integration has: verification passes (that uses the verify token), the
 * channel reports itself healthy, and then every inbound message fails
 * its signature check and is silently dropped. So the field is required
 * and labelled for what it actually is. Mirrors
 * PROVIDER_SIGNED_CHANNELS on the backend. */
export const PROVIDER_SIGNED_CHANNELS = ['whatsapp', 'messenger', 'instagram'] as const

export function usesProviderSignedSecret(channelType: string): boolean {
  return (PROVIDER_SIGNED_CHANNELS as readonly string[]).includes(channelType)
}

export function channelTypeLabel(channelType: string): string {
  return CHANNEL_TYPES.find((type) => type.value === channelType)?.label ?? channelType
}

export function hasGuidedSetup(channelType: string): boolean {
  return (GUIDED_CHANNEL_TYPES as readonly string[]).includes(channelType)
}

/** Matches the backend's `ChannelConfigResponse` — credentials and
 * webhook_secret are deliberately never echoed back once stored. */
export interface ChannelConfig {
  id: string
  channel_type: string
  display_name: string
  is_active: boolean
  created_at: string
  updated_at: string
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

export function channelTypeLabel(channelType: string): string {
  return CHANNEL_TYPES.find((type) => type.value === channelType)?.label ?? channelType
}

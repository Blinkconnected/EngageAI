import { EmailFields } from './EmailFields'
import { GenericJsonFields } from './GenericJsonFields'
import { MetaMessagingFields } from './MetaMessagingFields'
import { TelegramFields } from './TelegramFields'
import type { ChannelFieldsProps } from './types'
import { WebChatFields } from './WebChatFields'
import { WhatsAppFields } from './WhatsAppFields'

interface ChannelCredentialFieldsProps extends ChannelFieldsProps {
  channelType: string
}

/** The one place that decides which channel types get a guided,
 * per-field form vs. the generic JSON textarea — every Create/Edit
 * surface renders through here so the two never drift apart ("consistent
 * UX across all channels"). See channel-integration-spec.md. */
export function ChannelCredentialFields({
  channelType,
  credentials,
  onChange,
}: ChannelCredentialFieldsProps) {
  switch (channelType) {
    case 'whatsapp':
      return <WhatsAppFields credentials={credentials} onChange={onChange} />
    // Messenger and Instagram share the Graph API surface and need the
    // same two values, so they share the form — and no longer fall
    // through to the raw JSON textarea, which required knowing the exact
    // field names with no validation behind them.
    case 'messenger':
    case 'instagram':
      return (
        <MetaMessagingFields
          credentials={credentials}
          onChange={onChange}
          channelType={channelType}
        />
      )
    case 'telegram':
      return <TelegramFields credentials={credentials} onChange={onChange} />
    case 'email':
      return <EmailFields credentials={credentials} onChange={onChange} />
    case 'web_chat':
      return <WebChatFields />
    default:
      return <GenericJsonFields credentials={credentials} onChange={onChange} />
  }
}

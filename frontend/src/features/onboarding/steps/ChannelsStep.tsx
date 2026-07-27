import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button, Chip, List, ListItem, ListItemText, Stack, Typography } from '@mui/material'
import { ChannelCreateDialog } from '../../channels/ChannelCreateDialog'
import { channelTypeLabel } from '../../channels/types'
import { useAllChannelsQuery } from '../../channels/api'

export function ChannelsStep() {
  const { t } = useTranslation('onboarding')
  const [dialogChannelType, setDialogChannelType] = useState<string | null>(null)
  const channelsQuery = useAllChannelsQuery()

  return (
    <Stack spacing={3}>
      <Typography variant="body2" color="text.secondary">
        {t('ChannelsStep.description')}
      </Typography>

      <Stack direction="row" spacing={2} sx={{ flexWrap: 'wrap' }}>
        <Button variant="outlined" onClick={() => setDialogChannelType('whatsapp')}>
          {t('ChannelsStep.connectWhatsappButton')}
        </Button>
        <Button variant="outlined" onClick={() => setDialogChannelType('web_chat')}>
          {t('ChannelsStep.connectWebChatButton')}
        </Button>
        <Button variant="outlined" onClick={() => setDialogChannelType('telegram')}>
          {t('ChannelsStep.addAnotherChannelButton')}
        </Button>
      </Stack>

      {channelsQuery.data && channelsQuery.data.length > 0 && (
        <List dense sx={{ bgcolor: 'action.hover', borderRadius: 1 }}>
          {channelsQuery.data.map((channel) => (
            <ListItem key={channel.id}>
              <ListItemText
                primary={channel.display_name}
                secondary={channelTypeLabel(channel.channel_type)}
              />
              <Chip
                label={
                  channel.is_active
                    ? t('ChannelsStep.activeLabel')
                    : t('ChannelsStep.inactiveLabel')
                }
                size="small"
                color={channel.is_active ? 'success' : 'default'}
              />
            </ListItem>
          ))}
        </List>
      )}

      {dialogChannelType && (
        <ChannelCreateDialog
          key={dialogChannelType}
          open
          initialChannelType={dialogChannelType}
          onClose={() => setDialogChannelType(null)}
        />
      )}
    </Stack>
  )
}

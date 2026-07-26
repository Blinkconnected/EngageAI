import { useState } from 'react'
import { Button, Chip, List, ListItem, ListItemText, Stack, Typography } from '@mui/material'
import { ChannelCreateDialog } from '../../channels/ChannelCreateDialog'
import { channelTypeLabel } from '../../channels/types'
import { useAllChannelsQuery } from '../../channels/api'

export function ChannelsStep() {
  const [dialogChannelType, setDialogChannelType] = useState<string | null>(null)
  const channelsQuery = useAllChannelsQuery()

  return (
    <Stack spacing={3}>
      <Typography variant="body2" color="text.secondary">
        Connect the channels your team uses to talk to customers. All optional — you can add or
        remove channels any time from Channels in the sidebar.
      </Typography>

      <Stack direction="row" spacing={2} sx={{ flexWrap: 'wrap' }}>
        <Button variant="outlined" onClick={() => setDialogChannelType('whatsapp')}>
          Connect WhatsApp
        </Button>
        <Button variant="outlined" onClick={() => setDialogChannelType('web_chat')}>
          Connect Web Chat
        </Button>
        <Button variant="outlined" onClick={() => setDialogChannelType('telegram')}>
          Add another channel
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
                label={channel.is_active ? 'Active' : 'Inactive'}
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

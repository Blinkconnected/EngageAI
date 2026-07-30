import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import Box from '@mui/material/Box'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import IconButton from '@mui/material/IconButton'
import Tooltip from '@mui/material/Tooltip'
import VideocamOffOutlinedIcon from '@mui/icons-material/VideocamOffOutlined'
import OpenInFullOutlinedIcon from '@mui/icons-material/OpenInFullOutlined'

import { absoluteMediaUrl } from './mediaUrl'
import { reservedBoxFor } from './mediaLayout'
import { useMediaGallery } from './useMediaGallery'
import { useNearViewport } from './useNearViewport'
import type { Attachment } from '../types'

export function VideoAttachment({ attachment }: { attachment: Attachment }) {
  const { t } = useTranslation('conversationsExtra')
  const gallery = useMediaGallery()
  const [ref, isNear] = useNearViewport<HTMLDivElement>()
  const [failed, setFailed] = useState(false)

  const box = reservedBoxFor(attachment)
  const src = absoluteMediaUrl(attachment.media_url)

  if (failed || !src) {
    return (
      <Stack
        sx={{
          width: box.width,
          aspectRatio: box.aspectRatio,
          maxWidth: '100%',
          alignItems: 'center',
          justifyContent: 'center',
          gap: 0.5,
          bgcolor: 'action.hover',
          borderRadius: 1.5,
          color: 'text.secondary',
        }}
      >
        <VideocamOffOutlinedIcon fontSize="small" />
        <Typography variant="caption">{t('Media.videoUnsupported')}</Typography>
      </Stack>
    )
  }

  return (
    <Box
      ref={ref}
      sx={{
        width: box.width,
        maxWidth: '100%',
        aspectRatio: box.aspectRatio,
        position: 'relative',
        borderRadius: 1.5,
        overflow: 'hidden',
        bgcolor: 'common.black',
      }}
    >
      {isNear && (
        <Box
          component="video"
          src={src}
          controls
          // Metadata only until somebody presses play. `preload="auto"` on a
          // thread of videos would download every one of them; `none` would
          // mean no duration and a blank first frame, so the agent cannot
          // tell a 4-second clip from a 4-minute one.
          preload="metadata"
          playsInline
          onError={() => setFailed(true)}
          sx={{ display: 'block', width: '100%', height: '100%', objectFit: 'contain' }}
        />
      )}
      {gallery && (
        <Tooltip title={t('Media.expand')}>
          <IconButton
            size="small"
            onClick={() => gallery.openAttachment(attachment.id)}
            aria-label={t('Media.openVideoAriaLabel', { filename: attachment.filename })}
            sx={{
              position: 'absolute',
              top: 4,
              // Logical property, so it flips for Arabic without a second rule.
              insetInlineEnd: 4,
              bgcolor: 'rgba(0,0,0,0.55)',
              color: 'common.white',
              '&:hover': { bgcolor: 'rgba(0,0,0,0.75)' },
            }}
          >
            <OpenInFullOutlinedIcon fontSize="small" />
          </IconButton>
        </Tooltip>
      )}
    </Box>
  )
}

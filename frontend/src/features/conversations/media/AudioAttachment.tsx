import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import Box from '@mui/material/Box'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import GraphicEqOutlinedIcon from '@mui/icons-material/GraphicEqOutlined'
import MusicOffOutlinedIcon from '@mui/icons-material/MusicOffOutlined'

import { absoluteMediaUrl } from './mediaUrl'
import { useNearViewport } from './useNearViewport'
import { formatFileSize } from '../../../shared/utils/formatFileSize'
import type { Attachment } from '../types'

/** A voice note or audio file, played in place.
 *
 * No lightbox: there is nothing to look at, and full-screening an audio
 * player would be a worse experience than the inline one. */
export function AudioAttachment({ attachment }: { attachment: Attachment }) {
  const { t } = useTranslation('conversationsExtra')
  const [ref, isNear] = useNearViewport<HTMLDivElement>()
  const [failed, setFailed] = useState(false)

  const src = absoluteMediaUrl(attachment.media_url)

  return (
    <Stack
      ref={ref}
      spacing={0.75}
      sx={{
        // Fixed footprint: audio has no intrinsic shape to reserve, so the
        // player is the same size before and after it loads.
        width: 300,
        maxWidth: '100%',
        p: 1,
        borderRadius: 1.5,
        bgcolor: 'action.hover',
      }}
    >
      <Stack direction="row" spacing={0.75} sx={{ alignItems: 'center', minWidth: 0 }}>
        {failed ? (
          <MusicOffOutlinedIcon fontSize="small" color="action" />
        ) : (
          <GraphicEqOutlinedIcon fontSize="small" color="action" />
        )}
        <Typography variant="caption" noWrap title={attachment.filename} sx={{ flexGrow: 1 }}>
          {attachment.filename}
        </Typography>
        <Typography variant="caption" color="text.secondary">
          {formatFileSize(attachment.size_bytes)}
        </Typography>
      </Stack>
      {failed || !src ? (
        <Typography variant="caption" color="text.secondary">
          {t('Media.audioUnsupported')}
        </Typography>
      ) : (
        isNear && (
          <Box
            component="audio"
            src={src}
            controls
            preload="metadata"
            onError={() => setFailed(true)}
            aria-label={t('Media.audioAriaLabel', { filename: attachment.filename })}
            sx={{ width: '100%', display: 'block' }}
          />
        )
      )}
    </Stack>
  )
}

import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import Box from '@mui/material/Box'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import BrokenImageOutlinedIcon from '@mui/icons-material/BrokenImageOutlined'
import OpenInNewOutlinedIcon from '@mui/icons-material/OpenInNewOutlined'
import Button from '@mui/material/Button'

import { absoluteMediaUrl } from './mediaUrl'
import { reservedBoxFor } from './mediaLayout'
import { useMediaGallery } from './useMediaGallery'
import { useNearViewport } from './useNearViewport'
import type { Attachment } from '../types'

export function ImageAttachment({ attachment }: { attachment: Attachment }) {
  const { t } = useTranslation('conversationsExtra')
  const gallery = useMediaGallery()
  const [ref, isNear] = useNearViewport<HTMLDivElement>()
  const [loaded, setLoaded] = useState(false)
  const [failed, setFailed] = useState(false)

  const box = reservedBoxFor(attachment)
  const src = absoluteMediaUrl(attachment.media_url)

  const open = () => gallery?.openAttachment(attachment.id)

  if (failed || !src) {
    return (
      <Stack
        // Same footprint as the image would have had, so a failure does not
        // reflow the thread either.
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
          px: 2,
          textAlign: 'center',
        }}
      >
        <BrokenImageOutlinedIcon fontSize="small" />
        <Typography variant="caption">
          {attachment.needs_fallback ? t('Media.formatUnsupported') : t('Media.previewUnavailable')}
        </Typography>
        {src && (
          <Button
            size="small"
            startIcon={<OpenInNewOutlinedIcon fontSize="small" />}
            href={src}
            target="_blank"
            rel="noopener noreferrer"
          >
            {t('Media.openInNewTab')}
          </Button>
        )}
      </Stack>
    )
  }

  return (
    <Box
      ref={ref}
      component="button"
      type="button"
      onClick={open}
      aria-label={t('Media.openImageAriaLabel', { filename: attachment.filename })}
      sx={{
        // The box is reserved whether or not the bytes have arrived, so the
        // thread never jumps.
        width: box.width,
        maxWidth: '100%',
        aspectRatio: box.aspectRatio,
        p: 0,
        border: 'none',
        borderRadius: 1.5,
        overflow: 'hidden',
        position: 'relative',
        display: 'block',
        cursor: 'zoom-in',
        bgcolor: 'action.hover',
        // A visible focus ring: this is a button, and an agent tabbing
        // through a thread needs to see where they are.
        '&:focus-visible': {
          outline: '2px solid',
          outlineColor: 'primary.main',
          outlineOffset: 2,
        },
      }}
    >
      {isNear && (
        <Box
          component="img"
          src={src}
          alt={attachment.filename}
          // Native lazy loading as well as the observer: belt and braces,
          // and it lets the browser make its own better-informed decision
          // about priority.
          loading="lazy"
          decoding="async"
          onLoad={() => setLoaded(true)}
          onError={() => setFailed(true)}
          sx={{
            display: 'block',
            width: '100%',
            height: '100%',
            objectFit: 'cover',
            // Fades in rather than snapping, which reads as fast rather
            // than as flickering.
            opacity: loaded ? 1 : 0,
            transition: 'opacity 180ms ease-out',
            '@media (prefers-reduced-motion: reduce)': { transition: 'none' },
          }}
        />
      )}
    </Box>
  )
}

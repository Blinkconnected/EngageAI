import { useCallback, useState } from 'react'
import { useTranslation } from 'react-i18next'
import Box from '@mui/material/Box'
import Dialog from '@mui/material/Dialog'
import IconButton from '@mui/material/IconButton'
import Stack from '@mui/material/Stack'
import Tooltip from '@mui/material/Tooltip'
import Typography from '@mui/material/Typography'
import CircularProgress from '@mui/material/CircularProgress'
import CloseOutlinedIcon from '@mui/icons-material/CloseOutlined'
import ChevronLeftOutlinedIcon from '@mui/icons-material/ChevronLeftOutlined'
import ChevronRightOutlinedIcon from '@mui/icons-material/ChevronRightOutlined'
import DownloadOutlinedIcon from '@mui/icons-material/DownloadOutlined'
import OpenInNewOutlinedIcon from '@mui/icons-material/OpenInNewOutlined'

import { absoluteMediaUrl } from './mediaUrl'
import { useMediaGallery } from './useMediaGallery'
import type { Attachment } from '../types'
import { downloadAttachment } from '../api'
import { formatFileSize } from '../../../shared/utils/formatFileSize'

/** Full-screen viewer for the conversation's images and videos.
 *
 * MUI's `Dialog` supplies the focus trap and focus restoration — an agent
 * who opened the viewer with the keyboard lands back on the thumbnail they
 * came from, rather than at the top of the page. Reimplementing that by
 * hand is how focus management ends up subtly wrong.
 *
 * Arrow keys move between items; Escape closes (Dialog's own handler). The
 * keys are bound on the dialog content rather than the window, so they only
 * apply while it is open and cannot fight the thread's own shortcuts. */
export function MediaLightbox({ conversationId }: { conversationId: string }) {
  const { t } = useTranslation('conversationsExtra')
  const gallery = useMediaGallery()

  const openIndex = gallery?.openIndex ?? null
  const items = gallery?.items ?? []
  const current = openIndex === null ? null : items[openIndex]

  const handleKeyDown = useCallback(
    (event: React.KeyboardEvent) => {
      if (openIndex === null || !gallery) return
      // Not preventing default on anything else: Tab must still cycle
      // within the trap, and Escape is the Dialog's to handle.
      if (event.key === 'ArrowRight') {
        event.preventDefault()
        gallery.goTo(openIndex + 1)
      } else if (event.key === 'ArrowLeft') {
        event.preventDefault()
        gallery.goTo(openIndex - 1)
      }
    },
    [gallery, openIndex],
  )

  if (!gallery || openIndex === null || !current) return null

  const { attachment } = current
  const src = absoluteMediaUrl(attachment.media_url)
  const hasMultiple = items.length > 1

  return (
    <Dialog
      open
      onClose={gallery.close}
      fullScreen
      onKeyDown={handleKeyDown}
      slotProps={{
        paper: {
          // The label goes on the *paper*, because that is the element MUI
          // gives `role="dialog"`. Passed to `Dialog` it lands on the modal
          // root instead, and a screen reader announces an unnamed dialog —
          // which is exactly as useless as it sounds.
          'aria-label': t('Media.viewerAriaLabel', { filename: attachment.filename }),
          sx: {
            // Solid, not translucent. At any alpha the conversation shows
            // through and competes with the photo an agent opened the
            // viewer to look at — which is the one thing the viewer exists
            // to prevent. `backgroundImage: none` defeats MUI's elevation
            // overlay, which would otherwise lighten it in dark mode.
            bgcolor: '#000',
            backgroundImage: 'none',
          },
        },
      }}
    >
      <Stack sx={{ height: '100%', color: 'common.white' }}>
        {/* --- Toolbar --- */}
        <Stack
          direction="row"
          spacing={1}
          sx={{
            alignItems: 'center',
            p: 1,
            flexShrink: 0,
            borderBottom: '1px solid rgba(255,255,255,0.12)',
          }}
        >
          <Stack sx={{ minWidth: 0, flexGrow: 1, px: 1 }}>
            <Typography variant="body2" noWrap title={attachment.filename}>
              {attachment.filename}
            </Typography>
            <Typography variant="caption" sx={{ color: 'rgba(255,255,255,0.7)' }}>
              {formatFileSize(attachment.size_bytes)}
              {hasMultiple &&
                ` · ${t('Media.position', { index: openIndex + 1, total: items.length })}`}
            </Typography>
          </Stack>

          {src && (
            <Tooltip title={t('Media.openInNewTab')}>
              <IconButton
                href={src}
                target="_blank"
                rel="noopener noreferrer"
                aria-label={t('Media.openInNewTab')}
                sx={{ color: 'common.white' }}
              >
                <OpenInNewOutlinedIcon />
              </IconButton>
            </Tooltip>
          )}
          <Tooltip title={t('Media.download')}>
            <IconButton
              // The download endpoint, not the media one: it sends
              // Content-Disposition: attachment and the original filename,
              // which is what "Download" should mean.
              onClick={() => void downloadAttachment(conversationId, attachment)}
              aria-label={t('Media.downloadAriaLabel', { filename: attachment.filename })}
              sx={{ color: 'common.white' }}
            >
              <DownloadOutlinedIcon />
            </IconButton>
          </Tooltip>
          <Tooltip title={t('Media.close')}>
            <IconButton
              onClick={gallery.close}
              aria-label={t('Media.close')}
              sx={{ color: 'common.white' }}
            >
              <CloseOutlinedIcon />
            </IconButton>
          </Tooltip>
        </Stack>

        {/* --- The item itself --- */}
        <Box
          sx={{
            flexGrow: 1,
            minHeight: 0,
            position: 'relative',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            p: { xs: 1, sm: 3 },
          }}
        >
          {/* Keyed by attachment: React remounts it when the item changes,
              which resets loading and error state without an effect. An
              effect doing the same thing causes a cascading render, and gets
              it wrong on the first paint. */}
          <LightboxSurface key={attachment.id} attachment={attachment} src={src} />

          {hasMultiple && (
            <>
              <NavButton
                side="start"
                label={t('Media.previous')}
                onClick={() => gallery.goTo(openIndex - 1)}
                icon={<ChevronLeftOutlinedIcon />}
              />
              <NavButton
                side="end"
                label={t('Media.next')}
                onClick={() => gallery.goTo(openIndex + 1)}
                icon={<ChevronRightOutlinedIcon />}
              />
            </>
          )}
        </Box>
      </Stack>
    </Dialog>
  )
}

function LightboxSurface({
  attachment,
  src,
}: {
  attachment: Attachment
  src: string | null
}) {
  const { t } = useTranslation('conversationsExtra')
  const [loading, setLoading] = useState(true)
  const [failed, setFailed] = useState(false)

  if (failed || !src) {
    return (
      <Typography variant="body2" sx={{ color: 'rgba(255,255,255,0.8)' }}>
        {t('Media.previewUnavailable')}
      </Typography>
    )
  }

  const settle = () => setLoading(false)
  const fail = () => {
    setLoading(false)
    setFailed(true)
  }

  return (
    <>
      {loading && (
        <CircularProgress size={32} sx={{ position: 'absolute', color: 'common.white' }} />
      )}
      {attachment.kind === 'video' ? (
        <Box
          component="video"
          src={src}
          controls
          // Autoplays because opening a video full screen is an unambiguous
          // request to watch it. Muted is deliberately *not* set: a voice
          // note or a customer explaining a fault is the point.
          autoPlay
          playsInline
          onLoadedData={settle}
          onError={fail}
          sx={{ maxWidth: '100%', maxHeight: '100%', display: 'block' }}
        />
      ) : (
        <Box
          component="img"
          src={src}
          alt={attachment.filename}
          onLoad={settle}
          onError={fail}
          sx={{
            maxWidth: '100%',
            maxHeight: '100%',
            objectFit: 'contain',
            display: 'block',
            opacity: loading ? 0 : 1,
            transition: 'opacity 160ms ease-out',
            '@media (prefers-reduced-motion: reduce)': { transition: 'none' },
          }}
        />
      )}
    </>
  )
}

function NavButton({
  side,
  label,
  onClick,
  icon,
}: {
  side: 'start' | 'end'
  label: string
  onClick: () => void
  icon: React.ReactNode
}) {
  return (
    <IconButton
      onClick={onClick}
      aria-label={label}
      sx={{
        position: 'absolute',
        top: '50%',
        transform: 'translateY(-50%)',
        // Logical properties, so the arrows swap sides in Arabic without a
        // second set of rules — and `previous` stays on the reading-start
        // side in both directions.
        ...(side === 'start' ? { insetInlineStart: 8 } : { insetInlineEnd: 8 }),
        color: 'common.white',
        bgcolor: 'rgba(255,255,255,0.12)',
        '&:hover': { bgcolor: 'rgba(255,255,255,0.22)' },
      }}
    >
      {icon}
    </IconButton>
  )
}

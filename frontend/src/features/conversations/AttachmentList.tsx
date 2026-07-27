import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Box, IconButton, Skeleton, Stack, Tooltip, Typography } from '@mui/material'
import DescriptionOutlinedIcon from '@mui/icons-material/DescriptionOutlined'
import PictureAsPdfOutlinedIcon from '@mui/icons-material/PictureAsPdfOutlined'
import TableChartOutlinedIcon from '@mui/icons-material/TableChartOutlined'
import InsertDriveFileOutlinedIcon from '@mui/icons-material/InsertDriveFileOutlined'
import DownloadOutlinedIcon from '@mui/icons-material/DownloadOutlined'
import BrokenImageOutlinedIcon from '@mui/icons-material/BrokenImageOutlined'
import { formatFileSize } from '../../shared/utils/formatFileSize'
import { downloadAttachment, fetchAttachmentBlobUrl } from './api'
import type { Attachment } from './types'

function fileIconFor(contentType: string) {
  if (contentType === 'application/pdf') return <PictureAsPdfOutlinedIcon color="action" />
  if (contentType.includes('spreadsheet') || contentType === 'text/csv') {
    return <TableChartOutlinedIcon color="action" />
  }
  if (contentType.includes('word') || contentType === 'text/plain') {
    return <DescriptionOutlinedIcon color="action" />
  }
  return <InsertDriveFileOutlinedIcon color="action" />
}

/** Fetches the attachment bytes (auth-protected, so a plain `<img src>`
 * can't hit the download endpoint directly — see `api.ts`'s
 * `fetchAttachmentBlobUrl`) and renders it inline, clicking through to a
 * full download of the original file. */
function ImageAttachment({
  conversationId,
  attachment,
}: {
  conversationId: string
  attachment: Attachment
}) {
  const { t } = useTranslation('conversationsExtra')
  const [blobUrl, setBlobUrl] = useState<string | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let cancelled = false
    let url: string | null = null
    fetchAttachmentBlobUrl(conversationId, attachment.id)
      .then((objectUrl) => {
        if (cancelled) {
          URL.revokeObjectURL(objectUrl)
          return
        }
        url = objectUrl
        setBlobUrl(objectUrl)
      })
      .catch(() => {
        if (!cancelled) setFailed(true)
      })
    return () => {
      cancelled = true
      if (url) URL.revokeObjectURL(url)
    }
  }, [conversationId, attachment.id])

  if (failed) {
    return (
      <Stack
        sx={{
          width: 220,
          height: 160,
          alignItems: 'center',
          justifyContent: 'center',
          bgcolor: 'action.hover',
          borderRadius: 1,
          color: 'text.secondary',
        }}
        spacing={0.5}
      >
        <BrokenImageOutlinedIcon />
        <Typography variant="caption">{t('AttachmentList.previewUnavailable')}</Typography>
      </Stack>
    )
  }

  if (!blobUrl) {
    return <Skeleton variant="rounded" width={220} height={160} />
  }

  return (
    <Box
      component="button"
      type="button"
      onClick={() => void downloadAttachment(conversationId, attachment)}
      aria-label={t('AttachmentList.downloadAriaLabel', { filename: attachment.filename })}
      sx={{
        p: 0,
        border: 'none',
        borderRadius: 1,
        overflow: 'hidden',
        cursor: 'pointer',
        display: 'block',
        maxWidth: 240,
      }}
    >
      <Box
        component="img"
        src={blobUrl}
        alt={attachment.filename}
        sx={{ display: 'block', maxWidth: '100%', maxHeight: 220, borderRadius: 1 }}
      />
    </Box>
  )
}

function DocumentAttachment({
  conversationId,
  attachment,
}: {
  conversationId: string
  attachment: Attachment
}) {
  const { t } = useTranslation('conversationsExtra')
  return (
    <Stack
      direction="row"
      spacing={1}
      sx={{
        alignItems: 'center',
        p: 1,
        borderRadius: 1,
        bgcolor: 'action.hover',
        minWidth: 220,
        maxWidth: 280,
      }}
    >
      {fileIconFor(attachment.content_type)}
      <Stack sx={{ minWidth: 0, flexGrow: 1 }}>
        <Typography variant="body2" noWrap title={attachment.filename}>
          {attachment.filename}
        </Typography>
        <Typography variant="caption" color="text.secondary">
          {formatFileSize(attachment.size_bytes)}
        </Typography>
      </Stack>
      <Tooltip title={t('AttachmentList.downloadTooltip')}>
        <IconButton
          size="small"
          aria-label={t('AttachmentList.downloadAriaLabel', { filename: attachment.filename })}
          onClick={() => void downloadAttachment(conversationId, attachment)}
        >
          <DownloadOutlinedIcon fontSize="small" />
        </IconButton>
      </Tooltip>
    </Stack>
  )
}

export function AttachmentList({
  conversationId,
  attachments,
}: {
  conversationId: string
  attachments: Attachment[]
}) {
  if (attachments.length === 0) return null

  return (
    <Stack spacing={1} sx={{ mt: 1 }}>
      {attachments.map((attachment) =>
        attachment.content_type.startsWith('image/') ? (
          <ImageAttachment
            key={attachment.id}
            conversationId={conversationId}
            attachment={attachment}
          />
        ) : (
          <DocumentAttachment
            key={attachment.id}
            conversationId={conversationId}
            attachment={attachment}
          />
        ),
      )}
    </Stack>
  )
}

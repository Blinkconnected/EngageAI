import { useTranslation } from 'react-i18next'
import IconButton from '@mui/material/IconButton'
import Stack from '@mui/material/Stack'
import Tooltip from '@mui/material/Tooltip'
import Typography from '@mui/material/Typography'
import DescriptionOutlinedIcon from '@mui/icons-material/DescriptionOutlined'
import PictureAsPdfOutlinedIcon from '@mui/icons-material/PictureAsPdfOutlined'
import TableChartOutlinedIcon from '@mui/icons-material/TableChartOutlined'
import InsertDriveFileOutlinedIcon from '@mui/icons-material/InsertDriveFileOutlined'
import DownloadOutlinedIcon from '@mui/icons-material/DownloadOutlined'
import OpenInNewOutlinedIcon from '@mui/icons-material/OpenInNewOutlined'

import { formatFileSize } from '../../../shared/utils/formatFileSize'
import { downloadAttachment, attachmentDownloadHref } from '../api'
import type { Attachment } from '../types'

function iconFor(attachment: Attachment) {
  if (attachment.kind === 'document') return <PictureAsPdfOutlinedIcon color="action" />
  const type = attachment.content_type
  if (type.includes('spreadsheet') || type === 'text/csv') {
    return <TableChartOutlinedIcon color="action" />
  }
  if (type.includes('word') || type.startsWith('text/')) {
    return <DescriptionOutlinedIcon color="action" />
  }
  return <InsertDriveFileOutlinedIcon color="action" />
}

/** Anything not shown inline: documents, spreadsheets, archives.
 *
 * A PDF gets an "open" action as well as a download, because browsers render
 * PDFs natively and opening one in a tab is almost always what an agent
 * wants — reading it, not filing it. */
export function FileAttachment({
  conversationId,
  attachment,
}: {
  conversationId: string
  attachment: Attachment
}) {
  const { t } = useTranslation('conversationsExtra')
  const canOpenInTab = attachment.kind === 'document'

  return (
    <Stack
      direction="row"
      spacing={1}
      sx={{
        alignItems: 'center',
        p: 1,
        borderRadius: 1.5,
        bgcolor: 'action.hover',
        minWidth: 0,
        width: 300,
        maxWidth: '100%',
      }}
    >
      {iconFor(attachment)}
      <Stack sx={{ minWidth: 0, flexGrow: 1 }}>
        <Typography variant="body2" noWrap title={attachment.filename}>
          {attachment.filename}
        </Typography>
        <Typography variant="caption" color="text.secondary">
          {formatFileSize(attachment.size_bytes)}
        </Typography>
      </Stack>
      {canOpenInTab && (
        <Tooltip title={t('Media.openInNewTab')}>
          <IconButton
            size="small"
            component="a"
            href={attachmentDownloadHref(conversationId, attachment.id)}
            target="_blank"
            rel="noopener noreferrer"
            aria-label={t('Media.openInNewTab')}
          >
            <OpenInNewOutlinedIcon fontSize="small" />
          </IconButton>
        </Tooltip>
      )}
      <Tooltip title={t('Media.download')}>
        <IconButton
          size="small"
          aria-label={t('Media.downloadAriaLabel', { filename: attachment.filename })}
          onClick={() => void downloadAttachment(conversationId, attachment)}
        >
          <DownloadOutlinedIcon fontSize="small" />
        </IconButton>
      </Tooltip>
    </Stack>
  )
}

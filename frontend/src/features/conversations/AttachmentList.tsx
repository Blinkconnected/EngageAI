import Stack from '@mui/material/Stack'

import { AudioAttachment } from './media/AudioAttachment'
import { FileAttachment } from './media/FileAttachment'
import { ImageAttachment } from './media/ImageAttachment'
import { VideoAttachment } from './media/VideoAttachment'
import type { Attachment } from './types'

/** The one place that decides how an attachment is presented.
 *
 * Dispatches on the server-supplied `kind` rather than sniffing the content
 * type here: the backend already made that decision when it validated the
 * upload, and a second MIME table in the console would drift from it — with
 * the failure showing up as a broken `<video>` where a download link should
 * have been. */
export function AttachmentList({
  conversationId,
  attachments,
}: {
  conversationId: string
  attachments: Attachment[]
}) {
  if (attachments.length === 0) return null

  return (
    <Stack
      spacing={1}
      sx={{
        mt: 1,
        // Media sits at its natural size; the bubble does not stretch to it.
        alignItems: 'flex-start',
      }}
    >
      {attachments.map((attachment) => {
        // Anything the server did not give a media URL for cannot be
        // rendered inline whatever its kind claims — a pending or rejected
        // upload, for instance. Falling through to the file row is the
        // honest outcome.
        if (!attachment.inline || !attachment.media_url) {
          return (
            <FileAttachment
              key={attachment.id}
              conversationId={conversationId}
              attachment={attachment}
            />
          )
        }

        switch (attachment.kind) {
          case 'image':
            return <ImageAttachment key={attachment.id} attachment={attachment} />
          case 'video':
            return <VideoAttachment key={attachment.id} attachment={attachment} />
          case 'audio':
            return <AudioAttachment key={attachment.id} attachment={attachment} />
          default:
            return (
              <FileAttachment
                key={attachment.id}
                conversationId={conversationId}
                attachment={attachment}
              />
            )
        }
      })}
    </Stack>
  )
}

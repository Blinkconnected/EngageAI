import { useRef, useState } from 'react'
import { Alert, Box, Chip, IconButton, Stack, TextField, Tooltip } from '@mui/material'
import SendIcon from '@mui/icons-material/Send'
import AttachFileIcon from '@mui/icons-material/AttachFile'
import { extractErrorMessage } from '../../shared/api/errors'
import { useSendMessageMutation, useUploadAttachmentMutation } from './api'
import type { Attachment } from './types'

const TYPING_THROTTLE_MS = 3000

export function ReplyBox({
  conversationId,
  onTyping,
}: {
  conversationId: string
  onTyping?: (isTyping: boolean) => void
}) {
  const [body, setBody] = useState('')
  const [attachments, setAttachments] = useState<Attachment[]>([])
  const lastTypingSentAt = useRef(0)

  const sendMutation = useSendMessageMutation(conversationId)
  const uploadMutation = useUploadAttachmentMutation(conversationId)
  const fileInputRef = useRef<HTMLInputElement>(null)

  function handleBodyChange(value: string) {
    setBody(value)
    if (!onTyping) return
    const now = Date.now()
    if (now - lastTypingSentAt.current > TYPING_THROTTLE_MS) {
      lastTypingSentAt.current = now
      onTyping(true)
    }
  }

  function handleFileSelected(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    uploadMutation.mutate(file, {
      onSuccess: (attachment) => setAttachments((previous) => [...previous, attachment]),
    })
  }

  function handleSend() {
    if (!body.trim() && attachments.length === 0) return
    sendMutation.mutate(
      { body: body.trim() || null, attachment_ids: attachments.map((a) => a.id) },
      {
        onSuccess: () => {
          setBody('')
          setAttachments([])
          onTyping?.(false)
        },
      },
    )
  }

  return (
    <Box sx={{ borderTop: 1, borderColor: 'divider', p: 2 }}>
      {sendMutation.isError && (
        <Alert severity="error" sx={{ mb: 1 }}>
          {extractErrorMessage(sendMutation.error)}
        </Alert>
      )}
      {uploadMutation.isError && (
        <Alert severity="error" sx={{ mb: 1 }}>
          {extractErrorMessage(uploadMutation.error, 'Attachment failed to upload.')}
        </Alert>
      )}
      {attachments.length > 0 && (
        <Stack direction="row" spacing={1} sx={{ mb: 1, flexWrap: 'wrap' }}>
          {attachments.map((attachment) => (
            <Chip
              key={attachment.id}
              label={attachment.filename}
              onDelete={() =>
                setAttachments((previous) => previous.filter((a) => a.id !== attachment.id))
              }
            />
          ))}
        </Stack>
      )}
      <Stack direction="row" spacing={1} sx={{ alignItems: 'flex-end' }}>
        <input
          ref={fileInputRef}
          type="file"
          hidden
          onChange={handleFileSelected}
          aria-label="Attach a file"
        />
        <Tooltip title="Attach a file">
          <IconButton
            onClick={() => fileInputRef.current?.click()}
            disabled={uploadMutation.isPending}
            aria-label="Attach a file"
          >
            <AttachFileIcon />
          </IconButton>
        </Tooltip>
        <TextField
          multiline
          maxRows={4}
          fullWidth
          placeholder="Write a reply…"
          value={body}
          onChange={(event) => handleBodyChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault()
              handleSend()
            }
          }}
        />
        <Tooltip title="Send">
          <span>
            <IconButton
              color="primary"
              onClick={handleSend}
              disabled={sendMutation.isPending || (!body.trim() && attachments.length === 0)}
              aria-label="Send reply"
            >
              <SendIcon />
            </IconButton>
          </span>
        </Tooltip>
      </Stack>
    </Box>
  )
}

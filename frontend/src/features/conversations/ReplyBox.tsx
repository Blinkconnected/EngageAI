import { useRef, useState } from 'react'
import {
  Alert,
  Box,
  Chip,
  CircularProgress,
  IconButton,
  Stack,
  TextField,
  Tooltip,
} from '@mui/material'
import SendIcon from '@mui/icons-material/Send'
import AttachFileIcon from '@mui/icons-material/AttachFile'
import AutoAwesomeOutlinedIcon from '@mui/icons-material/AutoAwesomeOutlined'
import { extractErrorMessage } from '../../shared/api/errors'
import { usePermissions } from '../../shared/hooks/usePermissions'
import { useSuggestReplyMutation } from './aiApi'
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
  const [sendFailure, setSendFailure] = useState<string | null>(null)
  const lastTypingSentAt = useRef(0)

  const { hasPermission } = usePermissions()
  const sendMutation = useSendMessageMutation(conversationId)
  const uploadMutation = useUploadAttachmentMutation(conversationId)
  const suggestReplyMutation = useSuggestReplyMutation()
  const fileInputRef = useRef<HTMLInputElement>(null)

  function handleSuggestReply() {
    suggestReplyMutation.mutate(conversationId, {
      onSuccess: (suggestion) => setBody(suggestion),
    })
  }

  function handleBodyChange(value: string) {
    setBody(value)
    setSendFailure(null)
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
    setSendFailure(null)
    sendMutation.mutate(
      { body: body.trim() || null, attachment_ids: attachments.map((a) => a.id) },
      {
        onSuccess: (message) => {
          setBody('')
          setAttachments([])
          onTyping?.(false)
          // A failed send is still a 201 (the attempt was persisted so
          // it's diagnosable, not lost) — this isn't sendMutation.isError,
          // so it needs its own check to surface here, not just the
          // "Failed to send" chip on the message itself.
          if (message.status === 'failed') {
            const errorDetail = message.message_metadata.error
            setSendFailure(
              typeof errorDetail === 'string'
                ? errorDetail
                : 'The channel provider rejected this message.',
            )
          }
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
      {sendFailure && (
        <Alert severity="error" sx={{ mb: 1 }} onClose={() => setSendFailure(null)}>
          Message not delivered: {sendFailure}
        </Alert>
      )}
      {uploadMutation.isError && (
        <Alert severity="error" sx={{ mb: 1 }}>
          {extractErrorMessage(uploadMutation.error, 'Attachment failed to upload.')}
        </Alert>
      )}
      {suggestReplyMutation.isError && (
        <Alert severity="error" sx={{ mb: 1 }} onClose={() => suggestReplyMutation.reset()}>
          {extractErrorMessage(suggestReplyMutation.error, 'Could not suggest a reply.')}
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
        {hasPermission('ai.use') && (
          <Tooltip title="Suggest a reply with AI — replaces your draft, review before sending">
            <span>
              <IconButton
                onClick={handleSuggestReply}
                disabled={suggestReplyMutation.isPending}
                aria-label="Suggest a reply with AI"
              >
                {suggestReplyMutation.isPending ? (
                  <CircularProgress size={20} />
                ) : (
                  <AutoAwesomeOutlinedIcon />
                )}
              </IconButton>
            </span>
          </Tooltip>
        )}
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

import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
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
import BoltOutlinedIcon from '@mui/icons-material/BoltOutlined'
import { extractErrorMessage } from '../../shared/api/errors'
import { usePermissions } from '../../shared/hooks/usePermissions'
import { useSuggestReplyMutation } from './aiApi'
import { useSendMessageMutation, useUploadAttachmentMutation } from './api'
import { QuickReplyPicker } from './QuickReplyPicker'
import type { QuickReply } from '../quickReplies/types'
import type { Attachment } from './types'

const TYPING_THROTTLE_MS = 3000

export function ReplyBox({
  conversationId,
  onTyping,
}: {
  conversationId: string
  onTyping?: (isTyping: boolean) => void
}) {
  const { t } = useTranslation('conversationsCore')
  const [body, setBody] = useState('')
  const [attachments, setAttachments] = useState<Attachment[]>([])
  const [sendFailure, setSendFailure] = useState<string | null>(null)
  // Whether the current draft started life as an AI suggestion. Reported
  // to the backend on send as `is_ai_assisted`, which is what lets
  // reporting separate AI-assisted human replies from purely manual
  // ones. A ref, not state: it must never trigger a re-render, and it is
  // read only at send time.
  const draftCameFromAi = useRef(false)
  const lastTypingSentAt = useRef(0)
  const [quickReplyAnchor, setQuickReplyAnchor] = useState<HTMLElement | null>(null)
  // Seeded when the picker was opened by typing a slash, so `/ref` lands
  // on `/refund` without retyping it in the search box.
  const [quickReplyFilter, setQuickReplyFilter] = useState('')
  const quickReplyButtonRef = useRef<HTMLButtonElement>(null)
  const composerRef = useRef<HTMLTextAreaElement>(null)

  const { hasPermission } = usePermissions()
  const canUseQuickReplies = hasPermission('quick_replies.read')
  const sendMutation = useSendMessageMutation(conversationId)
  const uploadMutation = useUploadAttachmentMutation(conversationId)
  const suggestReplyMutation = useSuggestReplyMutation()
  const fileInputRef = useRef<HTMLInputElement>(null)

  function handleSuggestReply() {
    suggestReplyMutation.mutate(conversationId, {
      onSuccess: (suggestion) => {
        setBody(suggestion)
        draftCameFromAi.current = true
      },
    })
  }

  function openQuickReplies(filter = '') {
    setQuickReplyFilter(filter)
    setQuickReplyAnchor(quickReplyButtonRef.current)
  }

  function handleInsertQuickReply(reply: QuickReply) {
    setQuickReplyAnchor(null)
    // Replaces the draft rather than appending. A saved reply is a whole
    // answer somebody approved the wording of, and the only thing in the
    // box when the slash opened this was the slash itself. Appending
    // would also make picking twice silently produce a doubled message.
    setBody(reply.body)
    // Not AI-assisted: a human chose an approved phrase. Counting it as
    // AI would overstate what the model contributed.
    draftCameFromAi.current = false
    setSendFailure(null)
    // Back to the composer with the caret at the end, so the agent can
    // add a name or a date without reaching for the mouse.
    requestAnimationFrame(() => {
      const input = composerRef.current
      if (!input) return
      input.focus()
      input.setSelectionRange(reply.body.length, reply.body.length)
    })
  }

  function handleBodyChange(value: string) {
    // A slash typed as the very first character of an empty composer is
    // a request for a saved reply, so it opens the picker and is not
    // kept. Restricted to the first character on purpose: "12/05" and
    // "and/or" must stay typeable, and neither starts with one.
    if (canUseQuickReplies && body === '' && value === '/') {
      openQuickReplies()
      return
    }
    // Editing an AI draft keeps it AI-assisted (that's the point — it
    // measures AI's contribution, not verbatim sending). Clearing the
    // box entirely is the one thing that resets it: whatever is typed
    // next is genuinely the agent's own.
    if (value.trim() === '') draftCameFromAi.current = false
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
      {
        conversationId,
        payload: {
          body: body.trim() || null,
          attachment_ids: attachments.map((a) => a.id),
          is_ai_assisted: draftCameFromAi.current,
        },
      },
      {
        onSuccess: (message) => {
          setBody('')
          draftCameFromAi.current = false
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
                : t('ReplyBox.genericSendFailureFallback'),
            )
          }
        },
      },
    )
  }

  return (
    <Box
      sx={{
        // flexShrink: 0 — this is the composer's actual "stay pinned at
        // the bottom" contract: it's a static-flow sibling of
        // MessageThread inside a `minHeight: 0` flex column
        // (ConversationViewPage.tsx), and MessageThread is the only
        // region with `flexGrow`/its own `overflowY: auto`. Without this,
        // a tall composer (stacked error Alerts, attachment chips, a
        // multi-line draft) has no declared floor and could get
        // squeezed by the flexbox algorithm instead of always keeping
        // its full natural height with MessageThread absorbing 100% of
        // the remaining space — i.e. never losing access to it while
        // scrolling long message history, without needing
        // position: sticky/fixed (which would need its own z-index and
        // background-color handling over scrolled content instead).
        flexShrink: 0,
        borderTop: 1,
        borderColor: 'divider',
        p: 2,
        bgcolor: 'background.paper',
      }}
    >
      {sendMutation.isPaused && (
        <Alert severity="info" sx={{ mb: 1 }}>
          {t('ReplyBox.messageQueuedOfflineLabel')}
        </Alert>
      )}
      {sendMutation.isError && (
        <Alert severity="error" sx={{ mb: 1 }}>
          {extractErrorMessage(sendMutation.error)}
        </Alert>
      )}
      {sendFailure && (
        <Alert severity="error" sx={{ mb: 1 }} onClose={() => setSendFailure(null)}>
          {t('ReplyBox.messageNotDeliveredLabel', { reason: sendFailure })}
        </Alert>
      )}
      {uploadMutation.isError && (
        <Alert severity="error" sx={{ mb: 1 }}>
          {extractErrorMessage(uploadMutation.error, t('ReplyBox.uploadErrorFallback'))}
        </Alert>
      )}
      {suggestReplyMutation.isError && (
        <Alert severity="error" sx={{ mb: 1 }} onClose={() => suggestReplyMutation.reset()}>
          {extractErrorMessage(suggestReplyMutation.error, t('ReplyBox.suggestReplyErrorFallback'))}
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
          aria-label={t('ReplyBox.attachFileLabel')}
        />
        <Tooltip title={t('ReplyBox.attachFileLabel')}>
          <IconButton
            onClick={() => fileInputRef.current?.click()}
            disabled={uploadMutation.isPending}
            aria-label={t('ReplyBox.attachFileLabel')}
          >
            <AttachFileIcon />
          </IconButton>
        </Tooltip>
        {canUseQuickReplies && (
          <Tooltip title={t('ReplyBox.quickRepliesTooltip')}>
            <IconButton
              ref={quickReplyButtonRef}
              onClick={() => openQuickReplies()}
              aria-label={t('ReplyBox.quickRepliesAriaLabel')}
            >
              <BoltOutlinedIcon />
            </IconButton>
          </Tooltip>
        )}
        {hasPermission('ai.use') && (
          <Tooltip title={t('ReplyBox.suggestReplyTooltip')}>
            <span>
              <IconButton
                onClick={handleSuggestReply}
                disabled={suggestReplyMutation.isPending}
                aria-label={t('ReplyBox.suggestReplyAriaLabel')}
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
          placeholder={
            canUseQuickReplies
              ? t('ReplyBox.replyPlaceholderWithQuickReplies')
              : t('ReplyBox.replyPlaceholder')
          }
          inputRef={composerRef}
          // A placeholder is not a label: it disappears the moment
          // anybody types, and this field had nothing else. The name is
          // also what does not change when the placeholder does.
          slotProps={{ htmlInput: { 'aria-label': t('ReplyBox.replyAriaLabel') } }}
          value={body}
          onChange={(event) => handleBodyChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault()
              handleSend()
            }
          }}
        />
        <Tooltip title={t('ReplyBox.sendTooltip')}>
          <span>
            <IconButton
              color="primary"
              onClick={handleSend}
              disabled={sendMutation.isPending || (!body.trim() && attachments.length === 0)}
              aria-label={t('ReplyBox.sendAriaLabel')}
            >
              <SendIcon />
            </IconButton>
          </span>
        </Tooltip>
      </Stack>

      {/* Mounted only while open: that is what makes each open start
          clean, with the filter seeded from whatever followed the slash. */}
      {canUseQuickReplies && quickReplyAnchor && (
        <QuickReplyPicker
          open
          anchorEl={quickReplyAnchor}
          initialFilter={quickReplyFilter}
          onSelect={handleInsertQuickReply}
          onClose={() => setQuickReplyAnchor(null)}
        />
      )}
    </Box>
  )
}

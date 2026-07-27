import { useState } from 'react'
import { Alert, Box, Button, Paper, Stack, TextField, Typography } from '@mui/material'
import { LoadingState } from '../../shared/components/LoadingState'
import { ErrorState } from '../../shared/components/ErrorState'
import { EmptyState } from '../../shared/components/EmptyState'
import { extractErrorMessage } from '../../shared/api/errors'
import { formatRelativeTime } from '../../shared/utils/formatRelativeTime'
import { useCreateNoteMutation, useNotesQuery } from './api'

export function NotesPanel({ conversationId }: { conversationId: string }) {
  const [body, setBody] = useState('')
  const notesQuery = useNotesQuery(conversationId, { page: 1, page_size: 50 })
  const createMutation = useCreateNoteMutation(conversationId)

  function handleSubmit() {
    if (!body.trim()) return
    createMutation.mutate(body.trim(), { onSuccess: () => setBody('') })
  }

  // Newest-first from the API (matches message ordering) — reversed here
  // so the newest note lands next to the compose box, the same
  // oldest-to-newest-at-the-bottom convention MessageThread already
  // established for the adjacent Messages tab.
  const orderedNotes = [...(notesQuery.data?.items ?? [])].reverse()

  return (
    <Stack sx={{ flexGrow: 1, overflowY: 'auto', p: 2 }} spacing={2}>
      {notesQuery.isPending && <LoadingState label="Loading notes…" />}
      {notesQuery.isError && (
        <ErrorState error={notesQuery.error} onRetry={() => notesQuery.refetch()} />
      )}
      {notesQuery.data?.total === 0 && (
        <EmptyState
          title="No internal notes"
          description="Notes are visible only to your team, never to the customer."
        />
      )}
      {orderedNotes.map((note) => (
        <Paper key={note.id} variant="outlined" sx={{ p: 1.5, bgcolor: 'action.hover' }}>
          <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap' }}>
            {note.body}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            {formatRelativeTime(note.created_at)}
          </Typography>
        </Paper>
      ))}

      <Box sx={{ mt: 'auto' }}>
        {createMutation.isError && (
          <Alert severity="error" sx={{ mb: 1 }} onClose={() => createMutation.reset()}>
            {extractErrorMessage(createMutation.error, 'Could not add this note.')}
          </Alert>
        )}
        <TextField
          multiline
          minRows={2}
          fullWidth
          placeholder="Add an internal note (not visible to the customer)…"
          value={body}
          onChange={(event) => setBody(event.target.value)}
        />
        <Button
          variant="contained"
          size="small"
          sx={{ mt: 1 }}
          onClick={handleSubmit}
          disabled={createMutation.isPending || !body.trim()}
        >
          Add note
        </Button>
      </Box>
    </Stack>
  )
}

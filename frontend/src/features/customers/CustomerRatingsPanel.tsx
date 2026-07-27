import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Alert,
  Box,
  Button,
  IconButton,
  Paper,
  Rating,
  Stack,
  TextField,
  Typography,
} from '@mui/material'
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutlined'
import { LoadingState } from '../../shared/components/LoadingState'
import { ErrorState } from '../../shared/components/ErrorState'
import { EmptyState } from '../../shared/components/EmptyState'
import { extractErrorMessage } from '../../shared/api/errors'
import { formatRelativeTime } from '../../shared/utils/formatRelativeTime'
import { usePermissions } from '../../shared/hooks/usePermissions'
import {
  useCreateCustomerRatingMutation,
  useCustomerRatingsQuery,
  useDeleteCustomerRatingMutation,
} from './api'

/** Staff-only 1-5 star rating + optional note on a customer — never
 * shown on any customer-facing surface (see `CustomerInternalRating` in
 * types.ts). Mirrors `NotesPanel.tsx`'s shape (list + create form, no
 * inline edit) since the two features are structurally identical. */
export function CustomerRatingsPanel({ customerId }: { customerId: string }) {
  const { t } = useTranslation('customers')
  const { hasPermission } = usePermissions()
  const canManage = hasPermission('customers.manage')
  const [stars, setStars] = useState<number | null>(null)
  const [note, setNote] = useState('')

  const ratingsQuery = useCustomerRatingsQuery(customerId, { page: 1, page_size: 50 })
  const createMutation = useCreateCustomerRatingMutation(customerId)
  const deleteMutation = useDeleteCustomerRatingMutation(customerId)

  function handleSubmit() {
    if (!stars) return
    createMutation.mutate(
      { stars, note: note.trim() || null },
      {
        onSuccess: () => {
          setStars(null)
          setNote('')
        },
      },
    )
  }

  const ratings = ratingsQuery.data?.items ?? []

  return (
    <Stack spacing={2}>
      {canManage && (
        <Paper variant="outlined" sx={{ p: 2 }}>
          {createMutation.isError && (
            <Alert severity="error" sx={{ mb: 1.5 }} onClose={() => createMutation.reset()}>
              {extractErrorMessage(
                createMutation.error,
                t('CustomerRatingsPanel.addErrorFallback'),
              )}
            </Alert>
          )}
          <Typography variant="body2" sx={{ mb: 0.5 }}>
            {t('CustomerRatingsPanel.starsLabel')}
          </Typography>
          <Rating
            value={stars}
            onChange={(_event, value) => setStars(value)}
            aria-label={t('CustomerRatingsPanel.starsLabel')}
          />
          <TextField
            multiline
            minRows={2}
            fullWidth
            sx={{ mt: 1.5 }}
            placeholder={t('CustomerRatingsPanel.notePlaceholder')}
            value={note}
            onChange={(event) => setNote(event.target.value)}
          />
          <Button
            variant="contained"
            size="small"
            sx={{ mt: 1 }}
            onClick={handleSubmit}
            disabled={!stars || createMutation.isPending}
          >
            {t('CustomerRatingsPanel.addRatingButton')}
          </Button>
        </Paper>
      )}

      {ratingsQuery.isPending && <LoadingState label={t('CustomerRatingsPanel.loadingLabel')} />}
      {ratingsQuery.isError && (
        <ErrorState error={ratingsQuery.error} onRetry={() => ratingsQuery.refetch()} />
      )}
      {ratingsQuery.data?.total === 0 && (
        <EmptyState
          title={t('CustomerRatingsPanel.emptyTitle')}
          description={t('CustomerRatingsPanel.emptyDescription')}
        />
      )}

      {ratings.map((rating) => (
        <Paper key={rating.id} variant="outlined" sx={{ p: 1.5 }}>
          <Stack direction="row" sx={{ justifyContent: 'space-between', alignItems: 'flex-start' }}>
            <Box>
              <Rating value={rating.stars} readOnly size="small" />
              {rating.note && (
                <Typography variant="body2" sx={{ mt: 0.5, whiteSpace: 'pre-wrap' }}>
                  {rating.note}
                </Typography>
              )}
              <Typography variant="caption" color="text.secondary">
                {formatRelativeTime(rating.created_at)}
              </Typography>
            </Box>
            {canManage && (
              <IconButton
                size="small"
                aria-label={t('CustomerRatingsPanel.deleteRatingAriaLabel')}
                onClick={() => deleteMutation.mutate(rating.id)}
                disabled={deleteMutation.isPending}
              >
                <DeleteOutlineIcon fontSize="small" />
              </IconButton>
            )}
          </Stack>
        </Paper>
      ))}
    </Stack>
  )
}

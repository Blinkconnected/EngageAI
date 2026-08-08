import { useState } from 'react'
import {
  Alert,
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  Paper,
  Stack,
  Tab,
  Tabs,
  TextField,
  Typography,
} from '@mui/material'
import { useTranslation } from 'react-i18next'
import { PageHeader } from '../../shared/components/PageHeader'
import { LoadingState } from '../../shared/components/LoadingState'
import { ErrorState } from '../../shared/components/ErrorState'
import { EmptyState } from '../../shared/components/EmptyState'
import { extractErrorMessage } from '../../shared/api/errors'
import { useNow } from '../../shared/hooks/useNow'
import { formatElapsed } from '../../shared/utils/formatElapsed'
import {
  MIN_DELETION_REASON_LENGTH,
  useApproveDeletionMutation,
  useDeletionRequestsQuery,
  useRejectDeletionMutation,
  type ConversationDeletionRequest,
  type DeletionRequestStatus,
} from './deletionApi'

const PAGE_SIZE = 25

/** Pending first, because it is the only one that is work. The other two
 * are the record, and the record is read after the fact. */
const TABS: DeletionRequestStatus[] = ['pending', 'approved', 'rejected']

/**
 * The tenant administrator's queue of deletions to decide on.
 *
 * A deletion is the one irreversible thing anybody does in this product,
 * so this screen is built to be read rather than clicked through: the
 * reason an agent gave is the largest thing on each row, and neither
 * decision is a single unconfirmed click.
 *
 * Rejecting requires a note. Approving does not — the request's own
 * reason already stands — but a rejection contradicts it, and the person
 * who asked has to learn something rather than watching their request
 * quietly disappear.
 */
export function DeletionApprovalsPage() {
  const { t } = useTranslation('conversationsCore')
  const [status, setStatus] = useState<DeletionRequestStatus>('pending')
  const [deciding, setDeciding] = useState<{
    request: ConversationDeletionRequest
    decision: 'approve' | 'reject'
  } | null>(null)

  const query = useDeletionRequestsQuery({ page: 1, page_size: PAGE_SIZE, status })

  return (
    <>
      <PageHeader
        title={t('DeletionApprovals.title')}
        description={t('DeletionApprovals.description')}
      />

      <Tabs
        value={status}
        onChange={(_event, value: DeletionRequestStatus) => setStatus(value)}
        sx={{ mb: 2, borderBottom: 1, borderColor: 'divider' }}
      >
        {TABS.map((value) => (
          <Tab key={value} value={value} label={t(`DeletionApprovals.tab.${value}`)} />
        ))}
      </Tabs>

      {query.isPending ? (
        <LoadingState label={t('DeletionApprovals.loading')} />
      ) : query.isError ? (
        <ErrorState error={query.error} onRetry={() => query.refetch()} />
      ) : query.data.items.length === 0 ? (
        <EmptyState
          title={t(`DeletionApprovals.empty.${status}`)}
          description={t('DeletionApprovals.emptyDescription')}
        />
      ) : (
        <Stack spacing={2}>
          {query.data.items.map((request) => (
            <RequestCard
              key={request.id}
              request={request}
              onDecide={(decision) => setDeciding({ request, decision })}
            />
          ))}
        </Stack>
      )}

      {deciding && (
        <DecisionDialog
          request={deciding.request}
          decision={deciding.decision}
          onClose={() => setDeciding(null)}
        />
      )}
    </>
  )
}

function RequestCard({
  request,
  onDecide,
}: {
  request: ConversationDeletionRequest
  onDecide: (decision: 'approve' | 'reject') => void
}) {
  const { t } = useTranslation('conversationsCore')
  const now = useNow()
  const waiting = formatElapsed(request.created_at, now)

  return (
    <Paper variant="outlined" sx={{ p: 2 }}>
      <Stack
        direction="row"
        spacing={1}
        sx={{ alignItems: 'baseline', flexWrap: 'wrap', rowGap: 0.5, mb: 1 }}
      >
        <Typography variant="subtitle2" component="h2" sx={{ fontWeight: 700 }}>
          {request.customer_name ?? t('DeletionApprovals.unknownCustomer')}
        </Typography>
        <Chip
          size="small"
          label={t(`DeletionApprovals.tab.${request.status}`)}
          color={
            request.status === 'approved'
              ? 'error'
              : request.status === 'rejected'
                ? 'default'
                : 'warning'
          }
          variant={request.status === 'pending' ? 'filled' : 'outlined'}
        />
        <Box sx={{ flexGrow: 1 }} />
        <Typography variant="caption" color="text.secondary">
          {t('DeletionApprovals.askedBy', {
            name: request.requested_by_name ?? t('DeletionApprovals.someone'),
            duration: waiting ?? '',
          })}
        </Typography>
      </Stack>

      {/* The reason is the point of the screen, so it is set as prose
          rather than squeezed into a table cell. */}
      <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap', mb: 1 }}>
        {request.reason}
      </Typography>

      {request.status !== 'pending' && (
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
          {t('DeletionApprovals.decidedBy', {
            name: request.decided_by_name ?? t('DeletionApprovals.someone'),
            status: t(`DeletionApprovals.tab.${request.status}`).toLowerCase(),
          })}
          {request.decision_note ? ` — ${request.decision_note}` : ''}
        </Typography>
      )}

      {request.status === 'pending' && (
        <Stack direction="row" spacing={1} sx={{ mt: 1 }}>
          <Button size="small" color="error" variant="contained" onClick={() => onDecide('approve')}>
            {t('DeletionApprovals.approve')}
          </Button>
          <Button size="small" onClick={() => onDecide('reject')}>
            {t('DeletionApprovals.reject')}
          </Button>
        </Stack>
      )}
    </Paper>
  )
}

function DecisionDialog({
  request,
  decision,
  onClose,
}: {
  request: ConversationDeletionRequest
  decision: 'approve' | 'reject'
  onClose: () => void
}) {
  const { t } = useTranslation('conversationsCore')
  const [note, setNote] = useState('')
  const approveMutation = useApproveDeletionMutation()
  const rejectMutation = useRejectDeletionMutation()
  const mutation = decision === 'approve' ? approveMutation : rejectMutation

  const trimmed = note.trim()
  // Required in one direction only — see the page docstring.
  const noteTooShort = decision === 'reject' && trimmed.length < MIN_DELETION_REASON_LENGTH

  function handleConfirm() {
    if (noteTooShort) return
    mutation.mutate(
      { requestId: request.id, note: trimmed || undefined },
      { onSuccess: onClose },
    )
  }

  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>
        {decision === 'approve'
          ? t('DeletionApprovals.approveTitle')
          : t('DeletionApprovals.rejectTitle')}
      </DialogTitle>
      <DialogContent>
        <DialogContentText sx={{ mb: 2 }}>
          {decision === 'approve'
            ? t('DeletionApprovals.approveWarning', {
                customer: request.customer_name ?? t('DeletionApprovals.unknownCustomer'),
              })
            : t('DeletionApprovals.rejectExplanation')}
        </DialogContentText>

        {mutation.isError && (
          <Alert severity="error" sx={{ mb: 2 }} onClose={() => mutation.reset()}>
            {extractErrorMessage(mutation.error, t('DeletionApprovals.errorFallback'))}
          </Alert>
        )}

        <TextField
          autoFocus
          fullWidth
          multiline
          minRows={2}
          value={note}
          onChange={(event) => setNote(event.target.value)}
          label={
            decision === 'approve'
              ? t('DeletionApprovals.noteOptionalLabel')
              : t('DeletionApprovals.noteRequiredLabel')
          }
          error={decision === 'reject' && trimmed.length > 0 && noteTooShort}
          helperText={
            decision === 'reject'
              ? t('DeletionApprovals.noteHelp', { count: MIN_DELETION_REASON_LENGTH })
              : undefined
          }
        />
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>{t('DeletionApprovals.cancel')}</Button>
        <Button
          variant="contained"
          color={decision === 'approve' ? 'error' : 'primary'}
          onClick={handleConfirm}
          disabled={noteTooShort || mutation.isPending}
        >
          {mutation.isPending
            ? t('DeletionApprovals.working')
            : decision === 'approve'
              ? t('DeletionApprovals.confirmApprove')
              : t('DeletionApprovals.confirmReject')}
        </Button>
      </DialogActions>
    </Dialog>
  )
}

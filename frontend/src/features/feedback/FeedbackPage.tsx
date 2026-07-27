import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Paper,
  Rating,
  Stack,
  TextField,
  Typography,
} from '@mui/material'
import { Footer } from '../../shared/components/Footer'
import { extractErrorMessage } from '../../shared/api/errors'
import logoLight from '../../assets/logo-light.png'
import {
  useCsatContextQuery,
  useSubmitContactInfoMutation,
  useSubmitCsatResponseMutation,
} from './api'

/**
 * The public page a customer lands on after clicking their CSAT survey
 * link (see docs/architecture/reports-analytics.md's "Customer
 * Satisfaction" section) — mounted outside ProtectedRoute in
 * AppRoutes.tsx, same trust model as /login, /register, /changelog.
 * `conversationId` comes from the path, `token` from the query string;
 * neither is a session, so every request here goes through apiClient
 * with no Authorization header attached (the customer isn't signed in).
 */
// Each step is its own top-level return in FeedbackPage, so a distinct
// `key` per call site forces React to remount this on every step
// transition — otherwise it'd reuse the same DOM node (same type, same
// position) and the mount-only focus effect would never refire, leaving
// screen-reader/keyboard focus stuck on the previous step's heading.
function StepHeading({ children }: { children: ReactNode }) {
  const ref = useRef<HTMLHeadingElement>(null)

  useEffect(() => {
    ref.current?.focus()
  }, [])

  return (
    <Typography
      ref={ref}
      variant="h6"
      component="h1"
      tabIndex={-1}
      sx={{ textAlign: 'center', outline: 'none' }}
    >
      {children}
    </Typography>
  )
}

function PageShell({ children }: { children: ReactNode }) {
  return (
    <Box
      sx={{
        minHeight: '100%',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        bgcolor: 'background.default',
        p: 2,
      }}
    >
      <Paper elevation={2} sx={{ p: 4, width: 440, maxWidth: '100%' }}>
        <Stack spacing={2}>
          <Box
            component="img"
            src={logoLight}
            alt="Blink Engage"
            sx={{ height: 64, width: 'auto', display: 'block', mx: 'auto' }}
          />
          {children}
        </Stack>
      </Paper>
      <Footer />
    </Box>
  )
}

export function FeedbackPage() {
  const { conversationId = '' } = useParams()
  const [searchParams] = useSearchParams()
  const token = searchParams.get('token') ?? ''

  const contextQuery = useCsatContextQuery(conversationId, token)
  const contactInfoMutation = useSubmitContactInfoMutation(conversationId, token)
  const csatMutation = useSubmitCsatResponseMutation(conversationId, token)

  const [contactInfoProvided, setContactInfoProvided] = useState(false)
  const [email, setEmail] = useState('')
  const [phone, setPhone] = useState('')
  const [rating, setRating] = useState<number | null>(null)
  const [comment, setComment] = useState('')

  function handleContactInfoSubmit(event: FormEvent) {
    event.preventDefault()
    contactInfoMutation.mutate(
      { email: email.trim() || undefined, phone: phone.trim() || undefined },
      { onSuccess: () => setContactInfoProvided(true) },
    )
  }

  function handleRatingSubmit(event: FormEvent) {
    event.preventDefault()
    if (!rating) return
    csatMutation.mutate({ rating, comment: comment.trim() || undefined })
  }

  if (!conversationId || !token) {
    return (
      <PageShell>
        <Alert severity="error" data-testid="feedback-invalid-link">
          This feedback link is invalid.
        </Alert>
      </PageShell>
    )
  }

  if (contextQuery.isLoading) {
    return (
      <PageShell>
        <Box sx={{ display: 'flex', justifyContent: 'center', py: 2 }}>
          <CircularProgress size={32} />
        </Box>
      </PageShell>
    )
  }

  if (contextQuery.isError || !contextQuery.data) {
    return (
      <PageShell>
        <Alert severity="error" data-testid="feedback-error">
          {extractErrorMessage(
            contextQuery.error,
            'This feedback link is invalid or has expired.',
          )}
        </Alert>
      </PageShell>
    )
  }

  const context = contextQuery.data

  if (csatMutation.isSuccess || context.already_responded) {
    return (
      <PageShell>
        <StepHeading key="thank-you">Thank you for your feedback!</StepHeading>
        <Typography variant="body2" color="text.secondary" sx={{ textAlign: 'center' }}>
          We appreciate you taking the time to help us improve.
        </Typography>
      </PageShell>
    )
  }

  if (context.needs_contact_info && !contactInfoProvided) {
    return (
      <PageShell>
        <StepHeading key="contact-info">Before you go</StepHeading>
        <Typography variant="body2" color="text.secondary" sx={{ textAlign: 'center' }}>
          How can we reach you if we need to follow up? Please share your email address or
          phone number.
        </Typography>
        {contactInfoMutation.isError && (
          <Alert severity="error" data-testid="contact-info-error">
            {extractErrorMessage(contactInfoMutation.error)}
          </Alert>
        )}
        <Box component="form" onSubmit={handleContactInfoSubmit}>
          <Stack spacing={2}>
            <TextField
              label="Email"
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              fullWidth
            />
            <TextField
              label="Phone"
              value={phone}
              onChange={(event) => setPhone(event.target.value)}
              fullWidth
            />
            <Button
              type="submit"
              variant="contained"
              size="large"
              fullWidth
              disabled={contactInfoMutation.isPending || (!email.trim() && !phone.trim())}
            >
              {contactInfoMutation.isPending ? 'Saving…' : 'Continue'}
            </Button>
          </Stack>
        </Box>
      </PageShell>
    )
  }

  return (
    <PageShell>
      <StepHeading key="rating">How was your experience?</StepHeading>
      <Typography variant="body2" color="text.secondary" sx={{ textAlign: 'center' }}>
        Your feedback helps us serve you better.
      </Typography>
      {csatMutation.isError && (
        <Alert severity="error" data-testid="csat-submit-error">
          {extractErrorMessage(csatMutation.error)}
        </Alert>
      )}
      <Box component="form" onSubmit={handleRatingSubmit}>
        <Stack spacing={2} sx={{ alignItems: 'center' }}>
          <Rating
            size="large"
            value={rating}
            onChange={(_event, value) => setRating(value)}
            data-testid="csat-rating"
            aria-describedby="csat-rating-hint"
          />
          <Typography id="csat-rating-hint" variant="caption" color="text.secondary">
            {rating
              ? `You selected ${rating} star${rating === 1 ? '' : 's'}.`
              : 'Select a rating to enable submitting your feedback.'}
          </Typography>
          <TextField
            label="Additional comments (optional)"
            value={comment}
            onChange={(event) => setComment(event.target.value)}
            multiline
            minRows={3}
            fullWidth
          />
          <Button
            type="submit"
            variant="contained"
            size="large"
            fullWidth
            disabled={!rating || csatMutation.isPending}
          >
            {csatMutation.isPending ? 'Submitting…' : 'Submit feedback'}
          </Button>
        </Stack>
      </Box>
    </PageShell>
  )
}

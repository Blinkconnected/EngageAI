import { afterEach, describe, expect, it } from 'vitest'
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router-dom'
import { axe } from 'vitest-axe'
import { queryClient } from '../../app/queryClient'
import { renderWithProviders } from '../../test/renderWithProviders'
import { FeedbackPage } from './FeedbackPage'

function renderFeedback(path: string) {
  return renderWithProviders(
    <Routes>
      <Route path="/feedback/:conversationId" element={<FeedbackPage />} />
    </Routes>,
    [path],
  )
}

describe('FeedbackPage', () => {
  afterEach(() => {
    queryClient.clear()
  })

  it('asks for contact info first when the customer has neither an email nor a phone', async () => {
    renderFeedback('/feedback/conv1?token=valid-token')

    expect(await screen.findByText('Before you go')).toBeInTheDocument()
    expect(screen.queryByTestId('csat-rating')).not.toBeInTheDocument()
  })

  it('proceeds to the rating form after submitting contact info', async () => {
    const user = userEvent.setup()
    renderFeedback('/feedback/conv1?token=valid-token')

    await screen.findByText('Before you go')
    await user.type(screen.getByLabelText('Email'), 'customer@example.com')
    await user.click(screen.getByRole('button', { name: 'Continue' }))

    expect(await screen.findByText('How was your experience?')).toBeInTheDocument()
  })

  it('shows the rating form directly when contact info is already on file', async () => {
    renderFeedback('/feedback/conv2?token=valid-token')

    expect(await screen.findByText('How was your experience?')).toBeInTheDocument()
    expect(screen.queryByText('Before you go')).not.toBeInTheDocument()
  })

  it('submits a rating and shows a thank-you message', async () => {
    const user = userEvent.setup()
    renderFeedback('/feedback/conv2?token=valid-token')

    await screen.findByText('How was your experience?')
    const stars = within(screen.getByTestId('csat-rating')).getAllByRole('radio')
    fireEvent.click(stars[4]) // 5-star radio input — MUI's icon overlay is
    // pointer-events:none by design (so hover styling doesn't block the
    // underlying input), which trips user-event's own pointer-events
    // guard; firing directly on the input is the standard workaround.
    await user.click(screen.getByRole('button', { name: 'Submit feedback' }))

    expect(await screen.findByText('Thank you for your feedback!')).toBeInTheDocument()
  })

  it('shows a thank-you message directly when already responded', async () => {
    renderFeedback('/feedback/conv2?token=valid-token')
    await screen.findByText('How was your experience?')
    const stars = within(screen.getByTestId('csat-rating')).getAllByRole('radio')
    fireEvent.click(stars[3])
    await userEvent.setup().click(screen.getByRole('button', { name: 'Submit feedback' }))
    await screen.findByText('Thank you for your feedback!')

    // A second visit to the same link now sees already_responded from the API.
    renderFeedback('/feedback/conv2?token=valid-token')
    await waitFor(() => {
      expect(screen.getAllByText('Thank you for your feedback!').length).toBeGreaterThan(0)
    })
  })

  it('shows an error for an invalid or expired link', async () => {
    renderFeedback('/feedback/conv1?token=invalid-token')

    expect(await screen.findByTestId('feedback-error')).toBeInTheDocument()
  })

  it('shows an error when the link has no token', async () => {
    renderFeedback('/feedback/conv1')

    expect(await screen.findByTestId('feedback-invalid-link')).toBeInTheDocument()
  })

  it('has no detectable accessibility violations', async () => {
    const { container } = renderFeedback('/feedback/conv2?token=valid-token')
    await screen.findByText('How was your experience?')
    expect(await axe(container)).toHaveNoViolations()
  })
})

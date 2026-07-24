import { afterEach, describe, expect, it } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { axe } from 'vitest-axe'
import { store } from '../../app/store'
import { queryClient } from '../../app/queryClient'
import { loggedOut } from '../auth/authSlice'
import { renderAuthenticated } from '../../test/renderAuthenticated'
import { InboxPage } from './InboxPage'

describe('InboxPage', () => {
  afterEach(() => {
    store.dispatch(loggedOut())
    queryClient.clear()
  })

  it('lists conversations with resolved customer and channel names', async () => {
    renderAuthenticated(<InboxPage />)
    expect(await screen.findByText('Grace Blake')).toBeInTheDocument()
    expect(screen.getByText('Support Telegram')).toBeInTheDocument()
    expect(screen.getByText('Unassigned')).toBeInTheDocument()
  })

  it('has no detectable accessibility violations', async () => {
    const { container } = renderAuthenticated(<InboxPage />)
    await screen.findByText('Grace Blake')
    expect(await axe(container)).toHaveNoViolations()
  })

  it('filters to an empty list when switching to a status tab with no matches', async () => {
    const user = userEvent.setup()
    renderAuthenticated(<InboxPage />)
    await screen.findByText('Grace Blake')

    await user.click(screen.getByRole('tab', { name: /closed/i }))
    expect(await screen.findByText(/no conversations here/i)).toBeInTheDocument()
  })
})

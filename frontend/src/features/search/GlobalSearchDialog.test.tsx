import { afterEach, describe, expect, it } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes, useLocation } from 'react-router-dom'
import { axe } from 'vitest-axe'
import { store } from '../../app/store'
import { queryClient } from '../../app/queryClient'
import { loggedOut } from '../auth/authSlice'
import { renderAuthenticated } from '../../test/renderAuthenticated'
import { GlobalSearchDialog } from './GlobalSearchDialog'

/** Renders the dialog alongside a catch-all route that just echoes the
 * current path, so a test can assert where selecting a result navigated
 * to without mounting the whole app. */
function renderSearch() {
  return renderAuthenticated(
    <>
      <GlobalSearchDialog open onClose={() => {}} />
      <Routes>
        <Route path="*" element={<CurrentPath />} />
      </Routes>
    </>,
  )
}

/** Reads the router's own location — `window.location` never changes
 * under MemoryRouter, which keeps its history entirely in memory. */
function CurrentPath() {
  const location = useLocation()
  return <div data-testid="current-path">{location.pathname}</div>
}

describe('GlobalSearchDialog', () => {
  afterEach(() => {
    store.dispatch(loggedOut())
    queryClient.clear()
  })

  it('prompts for a longer query before searching', async () => {
    const user = userEvent.setup()
    renderSearch()

    expect(await screen.findByText(/type at least 2 characters/i)).toBeInTheDocument()

    await user.type(screen.getByLabelText(/search everything/i), 'g')
    expect(screen.getByText(/type at least 2 characters/i)).toBeInTheDocument()
  })

  it('groups results by entity type', async () => {
    const user = userEvent.setup()
    renderSearch()

    await user.type(screen.getByLabelText(/search everything/i), 'grace')

    // The seeded mock returns one hit per entity type (see
    // mocks/handlers/search.ts), so every group heading should appear.
    expect(await screen.findByText('Customers')).toBeInTheDocument()
    expect(screen.getByText('Conversations')).toBeInTheDocument()
    expect(screen.getByText('Knowledge base articles')).toBeInTheDocument()
    expect(screen.getByText('Queues')).toBeInTheDocument()
    expect(screen.getByText('Workflows')).toBeInTheDocument()
  })

  it('navigates to a customer when its result is selected', async () => {
    const user = userEvent.setup()
    renderSearch()

    await user.type(screen.getByLabelText(/search everything/i), 'grace')
    // Scoped to the Customers list so this can't accidentally click the
    // identically-titled Conversations hit (the mock seeds both as
    // "Grace Blake", exactly as the real thing would).
    const customersList = await screen.findByRole('list', { name: 'Customers' })
    await user.click(within(customersList).getByRole('button', { name: /Grace Blake/ }))

    await waitFor(() =>
      expect(screen.getByTestId('current-path')).toHaveTextContent('/customers/cust-1'),
    )
  })

  it('disables results for entity types that have no page yet', async () => {
    const user = userEvent.setup()
    renderSearch()

    await user.type(screen.getByLabelText(/search everything/i), 'grace')

    // Workflows, Teams, Quick replies and KB articles are searchable on
    // the backend but have no frontend route — their rows must be shown
    // (the match is real) but not clickable, with an explanation.
    const workflowsList = await screen.findByRole('list', { name: 'Workflows' })
    const workflowRow = within(workflowsList).getByRole('button', { name: /Grace onboarding/ })
    // MUI's ListItemButton renders as a <div role="button">, which can't
    // carry a real `disabled` attribute — aria-disabled is the actual
    // signal, for assistive tech and for userEvent alike.
    expect(workflowRow).toHaveAttribute('aria-disabled', 'true')
    expect(workflowRow).toHaveTextContent(/no page for this yet/i)

    // ...while a type that does have a page stays enabled.
    const customersList = screen.getByRole('list', { name: 'Customers' })
    expect(within(customersList).getByRole('button', { name: /Grace Blake/ })).not.toHaveAttribute(
      'aria-disabled',
      'true',
    )
  })

  it('shows an empty state when nothing matches', async () => {
    const user = userEvent.setup()
    renderSearch()

    await user.type(screen.getByLabelText(/search everything/i), 'zzzznomatch')

    expect(await screen.findByText(/no matches/i)).toBeInTheDocument()
  })

  it('has no detectable accessibility violations with results shown', async () => {
    const user = userEvent.setup()
    const { baseElement } = renderSearch()

    await user.type(screen.getByLabelText(/search everything/i), 'grace')
    await screen.findByRole('list', { name: 'Customers' })

    // baseElement, not container — a MUI Dialog renders into a portal
    // outside the container node.
    expect(await axe(baseElement)).toHaveNoViolations()
  })
})

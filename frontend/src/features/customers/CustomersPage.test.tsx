import { afterEach, describe, expect, it } from 'vitest'
import { screen } from '@testing-library/react'
import { axe } from 'vitest-axe'
import { store } from '../../app/store'
import { queryClient } from '../../app/queryClient'
import { loggedOut } from '../auth/authSlice'
import { renderAuthenticated } from '../../test/renderAuthenticated'
import { CustomersPage } from './CustomersPage'

describe('CustomersPage', () => {
  afterEach(() => {
    store.dispatch(loggedOut())
    queryClient.clear()
  })

  it('lists customers', async () => {
    renderAuthenticated(<CustomersPage />)
    expect(await screen.findByText('Grace Blake')).toBeInTheDocument()
    expect(screen.getByText('grace.blake@example.com')).toBeInTheDocument()
  })

  it('has no detectable accessibility violations', async () => {
    const { container } = renderAuthenticated(<CustomersPage />)
    await screen.findByText('Grace Blake')
    expect(await axe(container)).toHaveNoViolations()
  })
})

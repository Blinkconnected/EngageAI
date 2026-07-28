import { afterEach, describe, expect, it } from 'vitest'
import { screen } from '@testing-library/react'
import { axe } from 'vitest-axe'
import { store } from '../../app/store'
import { queryClient } from '../../app/queryClient'
import { loggedOut } from './authSlice'
import { renderWithProviders } from '../../test/renderWithProviders'
import { LoginPage } from './LoginPage'

describe('LoginPage', () => {
  afterEach(() => {
    store.dispatch(loggedOut())
    queryClient.clear()
  })

  it('renders the sign-in form', () => {
    renderWithProviders(<LoginPage />)

    expect(screen.getByLabelText(/^email/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/^password/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Sign in' })).toBeInTheDocument()
  })

  it('links to the standalone, public changelog page', () => {
    renderWithProviders(<LoginPage />)

    const link = screen.getByRole('link', { name: "What's new in this release" })
    expect(link).toHaveAttribute('href', '/changelog')
  })

  it('has no detectable accessibility violations', async () => {
    const { container } = renderWithProviders(<LoginPage />)
    expect(await axe(container)).toHaveNoViolations()
  })

  it('caps the sign-in card at 100% width so it never overflows a narrow viewport', () => {
    renderWithProviders(<LoginPage />)

    const card = screen.getByRole('button', { name: 'Sign in' }).closest('form')
    expect(card).not.toBeNull()
    expect(card).toHaveStyle({ maxWidth: '100%' })
  })
})

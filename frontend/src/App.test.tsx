import { afterEach, describe, expect, it } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { axe } from 'vitest-axe'
import { App } from './App'
import { store } from './app/store'
import { queryClient } from './app/queryClient'
import { loggedOut } from './features/auth/authSlice'
import { server } from './mocks/server'
import { API_BASE_URL } from './mocks/apiBaseUrl'

function goTo(path: string) {
  window.history.pushState({}, '', path)
}

describe('App', () => {
  afterEach(() => {
    store.dispatch(loggedOut())
    queryClient.clear()
    goTo('/')
  })

  it('shows the public site at the root when signed out', async () => {
    // The root used to redirect straight to sign-in, which told somebody
    // evaluating the product nothing. It is now the public site; the
    // redirect still applies to every other path (below).
    render(<App />)
    expect(await screen.findByRole('heading', { level: 1, name: /one place/i })).toBeInTheDocument()
  })

  it('redirects an unauthenticated visitor from a protected page to the login page', async () => {
    goTo('/agents')
    render(<App />)
    expect(await screen.findByText(/sign in to your workspace/i)).toBeInTheDocument()
  })

  it('renders the email and password fields on the login page', async () => {
    goTo('/login')
    render(<App />)
    expect(await screen.findByLabelText(/email/i)).toBeInTheDocument()
    expect(await screen.findByLabelText(/password/i)).toBeInTheDocument()
  })

  it('has no detectable accessibility violations on the login page', async () => {
    goTo('/login')
    const { container } = render(<App />)
    await screen.findByLabelText(/email/i)
    expect(await axe(container)).toHaveNoViolations()
  })

  it('logs a user in and lands on the live dashboard', async () => {
    const user = userEvent.setup()
    goTo('/login')
    render(<App />)

    await user.type(await screen.findByLabelText(/email/i), 'owner@example.com')
    await user.type(screen.getByLabelText(/password/i), 'correct-horse-battery-staple')
    await user.click(screen.getByRole('button', { name: /sign in/i }))

    expect(await screen.findByText('Acme Corp')).toBeInTheDocument()
    expect(await screen.findByText(/live snapshot of conversations/i)).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText('12')).toBeInTheDocument())
  })

  it('creates a company and lands on the live dashboard already signed in', async () => {
    const user = userEvent.setup()
    goTo('/register')
    render(<App />)

    await user.type(await screen.findByLabelText(/company name/i), 'Acme Corp')
    await user.type(screen.getByLabelText(/your full name/i), 'Ada Lovelace')
    await user.type(screen.getByLabelText(/^email/i), 'owner@example.com')
    await user.type(screen.getByLabelText(/^password/i), 'correct-horse-battery-staple-1')
    // The country picker sets the billing currency and is required: it
    // cannot be changed once the company has been invoiced.
    await user.click(screen.getByLabelText(/country/i))
    await user.click(await screen.findByRole('option', { name: 'United States' }))
    await user.click(screen.getByRole('button', { name: /create company/i }))

    expect(await screen.findByText('Acme Corp')).toBeInTheDocument()
  })

  it('shows an error message when login fails', async () => {
    server.use(
      http.post(`${API_BASE_URL}/auth/login`, () =>
        HttpResponse.json({ detail: 'Invalid credentials' }, { status: 401 }),
      ),
    )
    const user = userEvent.setup()
    render(<App />)

    await user.type(await screen.findByLabelText(/email/i), 'owner@example.com')
    await user.type(screen.getByLabelText(/password/i), 'wrong-password')
    await user.click(screen.getByRole('button', { name: /sign in/i }))

    expect(await screen.findByTestId('login-error')).toHaveTextContent('Invalid credentials')
  })

  it('shows an error state when the live dashboard fails to load', async () => {
    server.use(
      http.get(`${API_BASE_URL}/reports/live-dashboard`, () =>
        HttpResponse.json({ detail: 'Internal server error' }, { status: 500 }),
      ),
    )
    const user = userEvent.setup()
    goTo('/login')
    render(<App />)

    await user.type(await screen.findByLabelText(/email/i), 'owner@example.com')
    await user.type(screen.getByLabelText(/password/i), 'correct-horse-battery-staple')
    await user.click(screen.getByRole('button', { name: /sign in/i }))

    expect(
      await screen.findByText('Internal server error', {}, { timeout: 3000 }),
    ).toBeInTheDocument()
  })
})

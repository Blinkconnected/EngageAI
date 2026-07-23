import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { App } from './App'

describe('App', () => {
  it('redirects unauthenticated users to the login page', async () => {
    render(<App />)
    expect(await screen.findByText(/sign in to your workspace/i)).toBeInTheDocument()
  })

  it('renders the email and password fields on the login page', async () => {
    render(<App />)
    expect(await screen.findByLabelText(/email/i)).toBeInTheDocument()
    expect(await screen.findByLabelText(/password/i)).toBeInTheDocument()
  })
})

import { describe, expect, it, afterEach } from 'vitest'
import { screen } from '@testing-library/react'
import { axe } from 'vitest-axe'
import { queryClient } from '../../app/queryClient'
import { renderWithProviders } from '../../test/renderWithProviders'
import { ChangelogPage } from './ChangelogPage'

describe('ChangelogPage', () => {
  afterEach(() => {
    queryClient.clear()
  })

  it('is reachable without authentication and renders the changelog content', async () => {
    renderWithProviders(<ChangelogPage />, ['/changelog'])

    expect(screen.getByRole('heading', { name: "What's new" })).toBeInTheDocument()
    expect(await screen.findByText('Currently running')).toBeInTheDocument()
  })

  it('has no detectable accessibility violations', async () => {
    const { container } = renderWithProviders(<ChangelogPage />, ['/changelog'])
    await screen.findByText('Currently running')
    expect(await axe(container)).toHaveNoViolations()
  })
})

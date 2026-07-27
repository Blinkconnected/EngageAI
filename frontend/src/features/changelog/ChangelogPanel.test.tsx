import { afterEach, describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { screen } from '@testing-library/react'
import { axe } from 'vitest-axe'
import { queryClient } from '../../app/queryClient'
import { renderWithProviders } from '../../test/renderWithProviders'
import { server } from '../../mocks/server'
import { API_BASE_URL } from '../../mocks/apiBaseUrl'
import { ChangelogPanel } from './ChangelogPanel'

describe('ChangelogPanel', () => {
  afterEach(() => {
    queryClient.clear()
  })

  it('shows a loading state before the version/releases requests resolve', () => {
    renderWithProviders(<ChangelogPanel />)

    expect(screen.getByRole('status')).toBeInTheDocument()
    expect(screen.getByText('Loading changelog…')).toBeInTheDocument()
  })

  it("renders the currently-running version summary and the beta release's sections", async () => {
    renderWithProviders(<ChangelogPanel />)

    // Current-version summary (see mocks/handlers/changelog.ts): version
    // "1.0.0-beta.1", channel "Beta", released 2026-07-26.
    expect(await screen.findByText('Currently running')).toBeInTheDocument()
    const versionHeadings = screen.getAllByRole('heading', { name: '1.0.0-beta.1' })
    expect(versionHeadings.length).toBeGreaterThan(0)
    expect(screen.getAllByText('Beta').length).toBeGreaterThan(0)
    expect(screen.getAllByText(/Jul 26, 2026/).length).toBeGreaterThan(0)

    // The beta release card's non-empty subsections render...
    expect(screen.getByRole('heading', { name: 'Known Issues', level: 4 })).toBeInTheDocument()
    expect(screen.getByText(/Queue management — agents manually picking up/)).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Breaking Changes', level: 4 })).toBeInTheDocument()
    expect(screen.getByText('None yet (this is our first tracked release).')).toBeInTheDocument()

    // ...while its empty subsections (per the fixture, "Improved"/"Fixed"/
    // "Security"/"Deprecated" are all empty for 1.0.0-beta.1) do not.
    expect(screen.queryByRole('heading', { name: 'Security', level: 4 })).not.toBeInTheDocument()

    // The second fixture release ("1.0.0", still TBD) proves the
    // null-release_date -> "Unreleased" fallback and that a release with
    // every subsection empty renders no subsection headings at all.
    expect(screen.getByRole('heading', { name: '1.0.0', level: 3 })).toBeInTheDocument()
    expect(screen.getByText('Unreleased')).toBeInTheDocument()
    expect(
      screen.getByText('The finished, stable release, planned once pilot testing wraps up.'),
    ).toBeInTheDocument()
  })

  it("renders a bullet's **bold** label as real emphasis, not literal asterisks", async () => {
    const { container } = renderWithProviders(<ChangelogPanel />)

    // mocks/handlers/changelog.ts's first "added" bullet is
    // "**Sign-In, Access & Company Setup**: secure sign-in...".
    await screen.findByText('Currently running')
    expect(
      screen.getByText('Sign-In, Access & Company Setup', { selector: 'strong' }),
    ).toBeInTheDocument()
    expect(container.textContent).not.toContain('**')
  })

  it('shows an empty state when there is no published release history', async () => {
    server.use(http.get(`${API_BASE_URL}/releases`, () => HttpResponse.json([])))
    queryClient.clear()

    renderWithProviders(<ChangelogPanel />)

    expect(await screen.findByText('No releases yet')).toBeInTheDocument()
    // The version summary is a separate query and still renders.
    expect(screen.getByText('Currently running')).toBeInTheDocument()
  })

  it('has no detectable accessibility violations', async () => {
    const { container } = renderWithProviders(<ChangelogPanel />)
    await screen.findByText('Currently running')
    await screen.findByRole('heading', { name: '1.0.0', level: 3 })
    expect(await axe(container)).toHaveNoViolations()
  })
})

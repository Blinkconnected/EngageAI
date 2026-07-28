import { afterEach, describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
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

    // The second fixture release ("1.0.0", still TBD) is collapsed by
    // default — only the newest release starts expanded — so its body is
    // unmounted (see ReleaseAccordionItem's `unmountOnExit`) until opened.
    expect(screen.getByRole('heading', { name: '1.0.0', level: 3 })).toBeInTheDocument()
    expect(screen.getByText('Unreleased')).toBeInTheDocument()
    expect(
      screen.queryByText('The finished, stable release, planned once pilot testing wraps up.'),
    ).not.toBeInTheDocument()

    // Expanding it (proves the null-release_date -> "Unreleased" fallback
    // and that a release with every subsection empty renders no
    // subsection headings at all) reveals that body.
    const user = userEvent.setup()
    const secondReleaseHeading = screen.getByRole('heading', { name: '1.0.0', level: 3 })
    await user.click(within(secondReleaseHeading.closest('button')!).getByText('1.0.0'))
    expect(
      await screen.findByText('The finished, stable release, planned once pilot testing wraps up.'),
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

  it("labels the first tracked release 'Major' and shows its new-feature count in the collapsed header", async () => {
    renderWithProviders(<ChangelogPanel />)
    await screen.findByText('Currently running')

    // mocks/handlers/changelog.ts's "1.0.0-beta.1" has 15 "added" bullets
    // and no "improved"/"fixed" ones — it has nothing older with a
    // different SemVer core to diff against, so it's the "first release"
    // case (see releaseKind's doc comment), not a real major bump.
    const betaHeading = screen.getByRole('heading', { name: '1.0.0-beta.1', level: 3 })
    const betaSummary = betaHeading.closest('button')!
    expect(within(betaSummary).getByText('Major')).toBeInTheDocument()
    expect(within(betaSummary).getByText('15 new feature(s)')).toBeInTheDocument()
    expect(within(betaSummary).queryByText(/improvement\(s\)/)).not.toBeInTheDocument()
  })

  it('search filters the release list to only releases matching the term, across summary and bullet text', async () => {
    const user = userEvent.setup()
    renderWithProviders(<ChangelogPanel />)
    await screen.findByText('Currently running')
    expect(screen.getByRole('heading', { name: '1.0.0-beta.1', level: 3 })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '1.0.0', level: 3 })).toBeInTheDocument()

    // "wraps up" only appears in 1.0.0's summary — searching for it should
    // drop 1.0.0-beta.1 out of the list entirely.
    await user.type(screen.getByLabelText('Search release notes'), 'wraps up')
    expect(await screen.findByRole('heading', { name: '1.0.0', level: 3 })).toBeInTheDocument()
    expect(
      screen.queryByRole('heading', { name: '1.0.0-beta.1', level: 3 }),
    ).not.toBeInTheDocument()
  })

  it('shows a no-results state for a search term matching no release', async () => {
    const user = userEvent.setup()
    renderWithProviders(<ChangelogPanel />)
    await screen.findByText('Currently running')

    await user.type(
      screen.getByLabelText('Search release notes'),
      'nonexistent-feature-xyz',
    )
    expect(await screen.findByText('No matching releases')).toBeInTheDocument()
    expect(
      screen.getByText('Nothing in the release history matches "nonexistent-feature-xyz".'),
    ).toBeInTheDocument()
  })

  it('a #release-<version> URL hash expands and links directly to that release instead of the newest one', async () => {
    window.location.hash = `#release-1.0.0`
    renderWithProviders(<ChangelogPanel />)
    await screen.findByText('Currently running')

    // The linked release ("1.0.0"), not the newest one, starts expanded.
    expect(
      await screen.findByText('The finished, stable release, planned once pilot testing wraps up.'),
    ).toBeInTheDocument()
    window.location.hash = ''
  })
})

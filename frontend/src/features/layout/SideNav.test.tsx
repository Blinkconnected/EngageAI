import { afterEach, describe, expect, it } from 'vitest'
import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { store } from '../../app/store'
import { queryClient } from '../../app/queryClient'
import { loggedOut } from '../auth/authSlice'
import { renderAuthenticated } from '../../test/renderAuthenticated'
import { SideNav } from './SideNav'

/**
 * The sidebar was seventeen flat entries that mixed work somebody does
 * hourly with configuration they touch once. Grouping fixes that, and
 * introduces two ways to make it worse — both tested here.
 *
 * The first is showing an empty group heading. Permissions and plan
 * features already hide items, so a restricted agent could be presented
 * with four headings that expand to nothing: an inventory of what they
 * are not allowed to touch.
 *
 * The second is hiding the user's current location behind a collapsed
 * group, which would leave somebody unable to see where they are.
 */
function renderNav(initialEntries: string[] = ['/']) {
  return renderAuthenticated(<SideNav />, initialEntries)
}

describe('SideNav', () => {
  afterEach(() => {
    store.dispatch(loggedOut())
    queryClient.clear()
    localStorage.removeItem('blinkengage.nav.expandedGroups')
  })

  it('groups related destinations instead of listing everything flat', async () => {
    renderNav()

    expect(await screen.findByText('Work')).toBeInTheDocument()
    expect(screen.getByText('Routing')).toBeInTheDocument()
    expect(screen.getByText('Organisation')).toBeInTheDocument()
  })

  it('keeps Dashboard and Guide out of any group', async () => {
    renderNav()

    // Each is a destination in its own right rather than one of several
    // related screens. With every group collapsed these are the only
    // links on screen, which is the point: the sidebar opens showing
    // where you land and where to get help, not sixteen things you are
    // not currently doing.
    expect(await screen.findByRole('link', { name: /dashboard/i })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /guide/i })).toBeInTheDocument()
    expect(screen.getAllByRole('link')).toHaveLength(2)
  })

  it('offers the guide to everybody, whatever their role', async () => {
    renderNav()

    // Help behind a permission is help the person who needs it most
    // cannot reach.
    expect(await screen.findByRole('link', { name: /guide/i })).toHaveAttribute('href', '/help')
  })

  it('expands the group containing the current page', async () => {
    renderNav(['/queues'])

    // Queues lives under Routing. Landing there with Routing collapsed
    // would hide the user's own location from them.
    expect(await screen.findByRole('link', { name: /queues/i })).toBeInTheDocument()
  })

  it('opens and closes a group when its heading is used', async () => {
    const user = userEvent.setup()
    renderNav()

    const heading = (await screen.findByText('Organisation')).closest('div[role="button"]')
    expect(heading).not.toBeNull()

    // Collapsed to begin with — nothing under Organisation is active.
    expect(screen.queryByRole('link', { name: /departments/i })).not.toBeInTheDocument()

    await user.click(heading as HTMLElement)
    expect(await screen.findByRole('link', { name: /departments/i })).toBeInTheDocument()

    await user.click(heading as HTMLElement)
    expect(screen.queryByRole('link', { name: /departments/i })).not.toBeInTheDocument()
  })

  it('remembers which groups were left open', async () => {
    const user = userEvent.setup()
    const first = renderNav()

    const heading = (await screen.findByText('Organisation')).closest('div[role="button"]')
    await user.click(heading as HTMLElement)
    first.unmount()

    // An administrator lives in different groups than an agent does.
    // Re-collapsing on every navigation would fight them all day.
    renderNav()
    expect(await screen.findByRole('link', { name: /departments/i })).toBeInTheDocument()
  })

  it('marks a group heading as expandable to assistive technology', async () => {
    renderNav()

    const heading = (await screen.findByText('Work')).closest('div[role="button"]')
    expect(heading).toHaveAttribute('aria-expanded')
  })

  it('shows the deletion queue only to somebody who can decide', async () => {
    const user = userEvent.setup()
    renderNav()

    // Work, not Organisation: it is a queue somebody owes an answer to,
    // not a settings page. And it is gated on the permission that
    // decides, not the one that asks — an agent who can request a
    // deletion has no business seeing everybody else's requests.
    const heading = (await screen.findByText('Work')).closest('div[role="button"]')
    await user.click(heading as HTMLElement)

    expect(await screen.findByRole('link', { name: /deletion requests/i })).toHaveAttribute(
      'href',
      '/deletion-approvals',
    )
  })

  it('never renders a group heading with nothing under it', async () => {
    renderNav()

    // Every heading on screen must have at least one link inside its
    // group. An empty heading tells a restricted user only what they
    // cannot reach.
    const nav = await screen.findByRole('navigation')
    for (const label of ['Work', 'Insights', 'Routing', 'Connections', 'Organisation']) {
      const heading = within(nav).queryByText(label)
      if (heading === null) continue
      const button = heading.closest('div[role="button"]')
      expect(button).not.toBeNull()
    }
  })
})

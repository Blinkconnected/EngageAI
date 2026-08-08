/**
 * Saved replies, from the composer.
 *
 * The wording a team agreed on has been in the database since the
 * beginning with no way to reach it from the one screen where it gets
 * used. These cover the two ways in — the button and the slash — and the
 * two things that would quietly make the feature harmful: offering
 * wording the company withdrew, and eating a slash somebody meant to
 * type.
 */
import { afterEach, describe, expect, it } from 'vitest'
import { axe } from 'vitest-axe'
import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { store } from '../../app/store'
import { queryClient } from '../../app/queryClient'
import { loggedOut } from '../auth/authSlice'
import { renderAuthenticated } from '../../test/renderAuthenticated'
import { server } from '../../mocks/server'
import { API_BASE_URL } from '../../mocks/apiBaseUrl'
import { MOCK_USER } from '../../mocks/handlers/auth'
import { ReplyBox } from './ReplyBox'

function renderComposer() {
  return renderAuthenticated(<ReplyBox conversationId="conv-1" />)
}

function composer() {
  return screen.getByRole('textbox', { name: /^write a reply$/i })
}

async function findComposer() {
  return screen.findByRole('textbox', { name: /^write a reply$/i })
}

async function openPicker() {
  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: /insert a saved reply/i }))
  return screen.findByRole('list', { name: /saved replies/i })
}

describe('Saved replies in the composer', () => {
  afterEach(() => {
    store.dispatch(loggedOut())
    queryClient.clear()
  })

  it('opens from the composer and inserts the wording that was approved', async () => {
    const user = userEvent.setup()
    renderComposer()

    const list = await openPicker()
    await user.click(within(list).getByText('Refund policy'))

    expect(composer()).toHaveValue(
      'We refund any order within 30 days of delivery. Would you like me to start that for you?',
    )
  })

  it('opens when a slash is typed, and does not leave the slash behind', async () => {
    const user = userEvent.setup()
    renderComposer()

    await user.click(await findComposer())
    await user.keyboard('/')
    expect(await screen.findByRole('list', { name: /saved replies/i })).toBeInTheDocument()

    // Dismissed without choosing anything. The composer has to come back
    // empty: the slash was a command, not content, and leaving it behind
    // means the next thing typed starts with a stray character.
    // (Asserted after closing because the popover is modal — while it is
    // open the composer is correctly hidden from the accessibility tree.)
    await user.keyboard('{Escape}')

    expect(composer()).toHaveValue('')
  })

  it('leaves a slash alone when it is part of what somebody is writing', async () => {
    const user = userEvent.setup()
    renderComposer()

    // "12/05" and "and/or" have to stay typeable. Only a slash as the
    // very first character of an empty composer is a command.
    await user.type(await findComposer(), '12/05')

    expect(screen.queryByRole('list', { name: /saved replies/i })).not.toBeInTheDocument()
    expect(composer()).toHaveValue('12/05')
  })

  it('finds a reply by its shortcut, its title, or its wording', async () => {
    const user = userEvent.setup()
    renderComposer()
    await openPicker()
    const search = screen.getByRole('textbox', { name: /search saved replies/i })

    for (const term of ['hours', 'Opening', 'Sunday to Thursday']) {
      await user.clear(search)
      await user.type(search, term)
      const list = await screen.findByRole('list', { name: /saved replies/i })
      expect(within(list).getByText('Opening hours'), `no match for ${term}`).toBeInTheDocument()
    }
  })

  it('ranks the shortcut above wording that merely mentions the word', async () => {
    const user = userEvent.setup()
    renderComposer()
    await openPicker()

    await user.type(screen.getByRole('textbox', { name: /search saved replies/i }), 'refund')

    // Both replies contain "refund" — one as its shortcut, one only in
    // its body. Enter takes the first, so the order is the behaviour.
    const list = await screen.findByRole('list', { name: /saved replies/i })
    expect(within(list).getAllByRole('button')[0]).toHaveTextContent('Refund policy')
  })

  it('never offers wording the company has withdrawn', async () => {
    const user = userEvent.setup()
    renderComposer()
    await openPicker()

    await user.type(screen.getByRole('textbox', { name: /search saved replies/i }), 'refund')

    // `/oldpolicy` is inactive. Putting a retired phrase back in front of
    // a customer is worse than having no picker at all.
    expect(screen.queryByText('Withdrawn refund wording')).not.toBeInTheDocument()
  })

  it('is chosen with the keyboard alone', async () => {
    const user = userEvent.setup()
    renderComposer()
    await openPicker()

    await user.keyboard('{ArrowDown}{Enter}')

    expect(composer()).toHaveValue('We are open Sunday to Thursday, 9am to 6pm.')
  })

  it('says nobody has written any, rather than looking like a failed search', async () => {
    server.use(
      http.get(`${API_BASE_URL}/quick-replies`, () =>
        HttpResponse.json({ items: [], total: 0, page: 1, page_size: 100 }),
      ),
    )
    renderComposer()
    await userEvent
      .setup()
      .click(await screen.findByRole('button', { name: /insert a saved reply/i }))

    expect(await screen.findByText(/no saved replies yet/i)).toBeInTheDocument()
  })

  it('has no detectable accessibility violations while open', async () => {
    const { container } = renderComposer()
    await openPicker()

    expect(await axe(container)).toHaveNoViolations()
  })

  it('is not offered at all without permission to read saved replies', async () => {
    server.use(
      http.get(`${API_BASE_URL}/auth/me`, () =>
        HttpResponse.json({
          ...MOCK_USER,
          permissions: MOCK_USER.permissions.filter((code) => code !== 'quick_replies.read'),
        }),
      ),
    )
    queryClient.clear()
    renderComposer()

    // Hidden rather than disabled, and the slash goes back to being an
    // ordinary character.
    expect(await findComposer()).toHaveAttribute('placeholder', 'Write a reply…')
    expect(screen.queryByRole('button', { name: /insert a saved reply/i })).not.toBeInTheDocument()
  })
})

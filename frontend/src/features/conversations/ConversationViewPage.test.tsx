import { afterEach, describe, expect, it } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router-dom'
import { axe } from 'vitest-axe'
import { store } from '../../app/store'
import { queryClient } from '../../app/queryClient'
import { loggedOut } from '../auth/authSlice'
import { renderAuthenticated } from '../../test/renderAuthenticated'
import { ConversationViewPage } from './ConversationViewPage'

function renderConversationView() {
  return renderAuthenticated(
    <Routes>
      <Route path="/conversations/:conversationId" element={<ConversationViewPage />} />
    </Routes>,
    ['/conversations/conv-1'],
  )
}

// "Grace Blake" legitimately renders twice once the page has loaded — once
// in the page header, once in the sidebar's "Customer" field — so it's an
// ambiguous match for getByText/findByText (which require exactly one).
// The Status field is unique and only mounts once the conversation and its
// sidebar have loaded, so it's used as the "page is ready" signal instead.
async function waitForLoaded() {
  return screen.findByLabelText(/^status/i)
}

describe('ConversationViewPage', () => {
  afterEach(() => {
    store.dispatch(loggedOut())
    queryClient.clear()
  })

  it('shows the customer name and the seeded message', async () => {
    renderConversationView()
    await waitForLoaded()
    expect(await screen.findAllByText('Grace Blake')).not.toHaveLength(0)
    expect(await screen.findByText('Hi, I need help with my order.')).toBeInTheDocument()
  })

  it('has no detectable accessibility violations', async () => {
    const { container } = renderConversationView()
    await waitForLoaded()
    expect(await axe(container)).toHaveNoViolations()
  })

  it('sends a reply and it appears in the thread', async () => {
    const user = userEvent.setup()
    renderConversationView()
    await screen.findByText('Hi, I need help with my order.')

    await user.type(screen.getByPlaceholderText(/write a reply/i), 'Sure, happy to help!')
    await user.click(screen.getByRole('button', { name: /send reply/i }))

    expect(await screen.findByText('Sure, happy to help!')).toBeInTheDocument()
  })

  it('surfaces a diagnosable error when the channel provider rejects a send', async () => {
    const user = userEvent.setup()
    renderConversationView()
    await screen.findByText('Hi, I need help with my order.')

    await user.type(screen.getByPlaceholderText(/write a reply/i), 'TRIGGER_SEND_FAILURE')
    await user.click(screen.getByRole('button', { name: /send reply/i }))

    expect(await screen.findByText(/message not delivered/i)).toBeInTheDocument()
    expect(screen.getByText('Failed to send')).toBeInTheDocument()
  })

  it('changes the conversation status', async () => {
    const user = userEvent.setup()
    renderConversationView()
    const statusField = await waitForLoaded()

    await user.click(statusField)
    await user.click(await screen.findByRole('option', { name: 'Resolved' }))

    await waitFor(() => expect(screen.getByLabelText(/^status/i)).toHaveTextContent('Resolved'))
  })

  // jsdom's FormData/File polyfill doesn't preserve File.name through a
  // real multipart round trip (verified independently: even a bare
  // `new Request(..., {body: formData}).formData()` loses it in this
  // environment) — content_type does survive, though, which is what
  // AttachmentList actually branches on to choose image-vs-document
  // rendering, so these assert on that rendering decision rather than on
  // filename text a real browser would preserve but jsdom can't.
  //
  // The inline *image* preview specifically isn't covered here: it fetches
  // its blob eagerly on mount, and jsdom's Blob doesn't implement
  // `.stream()`, which MSW's Response construction needs — an unrelated
  // tooling gap (confirmed independent of this app's code), not something
  // a test workaround can route around. AttachmentList.test.tsx covers the
  // image-vs-document rendering decision directly with the network layer
  // mocked out; the real fetch-and-render path is covered by live
  // verification against the production Docker stack in an actual browser.
  it('sends a reply with a document attachment showing a size and download button', async () => {
    const user = userEvent.setup()
    renderConversationView()
    await screen.findByText('Hi, I need help with my order.')

    const file = new File(['%PDF-1.4 fake pdf bytes'], 'invoice.pdf', {
      type: 'application/pdf',
    })
    await user.upload(screen.getByLabelText(/attach a file/i, { selector: 'input' }), file)
    await waitFor(() => expect(screen.getByRole('button', { name: /send reply/i })).toBeEnabled())

    await user.click(screen.getByRole('button', { name: /send reply/i }))

    await waitFor(() =>
      expect(screen.getByRole('button', { name: /^download/i })).toBeInTheDocument(),
    )
    // Size text ("9 B", "1.2 KB", ...) from formatFileSize, proving the
    // document row rendered with real metadata, not just a bare button.
    expect(screen.getByText(/^\d+(\.\d+)?\s?(B|KB|MB|GB)$/)).toBeInTheDocument()
  })

  it('adds an internal note', async () => {
    const user = userEvent.setup()
    renderConversationView()
    await waitForLoaded()

    await user.click(screen.getByRole('tab', { name: /internal notes/i }))
    await user.type(
      screen.getByPlaceholderText(/add an internal note/i),
      'Customer seems frustrated.',
    )
    await user.click(screen.getByRole('button', { name: /add note/i }))

    expect(await screen.findByText('Customer seems frustrated.')).toBeInTheDocument()
  })
})

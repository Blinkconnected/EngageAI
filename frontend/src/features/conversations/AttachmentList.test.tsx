import { afterEach, describe, expect, it, vi } from 'vitest'
import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { store } from '../../app/store'
import { queryClient } from '../../app/queryClient'
import { loggedOut } from '../auth/authSlice'
import { renderAuthenticated } from '../../test/renderAuthenticated'
import { AttachmentList } from './AttachmentList'
import { MediaGalleryProvider } from './media/mediaGallery'
import { MediaLightbox } from './media/MediaLightbox'
import type { Attachment, Message } from './types'

// `./api` is mocked because jsdom's Blob has no `.stream()`, which breaks
// MSW's Response construction for blob-typed responses. Inline media no
// longer goes through a blob at all — it uses the signed `media_url`
// directly — so only the explicit Download action needs stubbing.
vi.mock('./api', () => ({
  downloadAttachment: vi.fn().mockResolvedValue(undefined),
  attachmentDownloadHref: (c: string, a: string) => `/api/v1/conversations/${c}/att/${a}`,
}))

import { downloadAttachment } from './api'

function attachment(overrides: Partial<Attachment> = {}): Attachment {
  return {
    id: 'att-img',
    filename: 'photo.png',
    content_type: 'image/png',
    size_bytes: 204_800,
    validation_status: 'approved',
    message_id: 'msg-1',
    created_at: '2026-01-01T00:00:00Z',
    kind: 'image',
    inline: true,
    needs_fallback: false,
    width: 1600,
    height: 900,
    media_url: '/api/v1/conversations/conv-1/attachments/att-img/media?exp=1&sig=abc',
    ...overrides,
  }
}

const DOCUMENT = attachment({
  id: 'att-doc',
  filename: 'invoice.pdf',
  content_type: 'application/pdf',
  size_bytes: 51_200,
  kind: 'document',
  inline: false,
  width: null,
  height: null,
  media_url: null,
})

function renderList(attachments: Attachment[]) {
  return renderAuthenticated(
    <AttachmentList conversationId="conv-1" attachments={attachments} />,
  )
}

/** The thread's real wrapper, so clicking an image opens the viewer. */
function renderInThread(attachments: Attachment[]) {
  const messages: Message[] = [
    {
      id: 'msg-1',
      conversation_id: 'conv-1',
      direction: 'inbound',
      body: 'Here you go',
      created_at: '2026-01-01T00:00:00Z',
      message_metadata: {},
      attachments,
    } as unknown as Message,
  ]
  return renderAuthenticated(
    <MediaGalleryProvider messages={messages}>
      <AttachmentList conversationId="conv-1" attachments={attachments} />
      <MediaLightbox conversationId="conv-1" />
    </MediaGalleryProvider>,
  )
}

describe('AttachmentList', () => {
  afterEach(() => {
    store.dispatch(loggedOut())
    queryClient.clear()
  })

  it('renders nothing for an empty attachment list', () => {
    const { container } = renderList([])
    expect(container).toBeEmptyDOMElement()
  })

  it('shows an image inline from its signed URL, with no auth round trip', async () => {
    renderList([attachment()])

    const img = await screen.findByAltText('photo.png')
    expect(img.getAttribute('src')).toContain('/attachments/att-img/media')
    // Native lazy loading as well as the observer, so the browser can make
    // its own priority decision.
    expect(img).toHaveAttribute('loading', 'lazy')
  })

  it('reserves the image’s real shape before it loads', async () => {
    // The anti-layout-shift guarantee: a 16:9 image reserves 16:9, so a
    // thread of photos does not reflow as they arrive and an agent does not
    // lose their place mid-sentence.
    renderList([attachment({ width: 1600, height: 900 })])

    const button = await screen.findByRole('button', { name: /view photo\.png/i })
    expect(button).toHaveStyle({ aspectRatio: `${1600 / 900}` })
  })

  it('falls back to a default shape when dimensions are unknown', async () => {
    renderList([attachment({ width: null, height: null })])
    const button = await screen.findByRole('button', { name: /view photo\.png/i })
    expect(button).toHaveStyle({ aspectRatio: `${4 / 3}` })
  })

  it('plays video inline with metadata-only preloading', async () => {
    // `preload="auto"` on a thread of videos would download every one of
    // them; `none` would leave no duration, so an agent cannot tell a
    // 4-second clip from a 4-minute one.
    const { container } = renderList([
      attachment({ id: 'att-vid', filename: 'clip.mp4', content_type: 'video/mp4', kind: 'video' }),
    ])

    const video = container.querySelector('video')
    expect(video).toHaveAttribute('preload', 'metadata')
    expect(video).toHaveAttribute('controls')
  })

  it('plays audio inline and names it for screen readers', async () => {
    const { container } = renderList([
      attachment({
        id: 'att-aud',
        filename: 'voice-note.ogg',
        content_type: 'audio/ogg',
        kind: 'audio',
        width: null,
        height: null,
      }),
    ])

    const audio = container.querySelector('audio')
    expect(audio).toHaveAttribute('controls')
    expect(audio).toHaveAttribute('aria-label', expect.stringContaining('voice-note.ogg'))
  })

  it('offers a document as a download and an open-in-new-tab', async () => {
    renderList([DOCUMENT])

    expect(screen.getByText('invoice.pdf')).toBeInTheDocument()
    expect(screen.getByText('50 KB')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /open in a new tab/i })).toBeInTheDocument()

    await userEvent.setup().click(screen.getByRole('button', { name: /download invoice\.pdf/i }))
    expect(downloadAttachment).toHaveBeenCalledWith('conv-1', DOCUMENT)
  })

  it('treats an attachment with no media URL as a file whatever its kind says', async () => {
    // A pending or rejected upload. Rendering a broken <img> for it would
    // look like the customer sent a corrupt file.
    renderList([attachment({ media_url: null, inline: false })])

    expect(screen.queryByAltText('photo.png')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /download photo\.png/i })).toBeInTheDocument()
  })

  it('says so when the browser cannot decode the format', async () => {
    renderList([
      attachment({ filename: 'IMG_0042.HEIC', content_type: 'image/heic', needs_fallback: true }),
    ])

    const img = await screen.findByAltText('IMG_0042.HEIC')
    // Simulate the browser refusing it, which is what actually happens for
    // HEIC outside Safari.
    const { fireEvent } = await import('@testing-library/react')
    fireEvent.error(img)

    expect(await screen.findByText(/can't display this image format/i)).toBeInTheDocument()
  })
})

describe('the media viewer', () => {
  afterEach(() => {
    store.dispatch(loggedOut())
    queryClient.clear()
  })

  it('opens full screen when an image is clicked', async () => {
    renderInThread([attachment()])
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: /view photo\.png/i }))

    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText('photo.png')).toBeInTheDocument()
  })

  it('moves between attachments with the arrow keys', async () => {
    const first = attachment({ id: 'a1', filename: 'first.png' })
    const second = attachment({ id: 'a2', filename: 'second.png' })
    renderInThread([first, second])
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: /view first\.png/i }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText(/1 of 2/)).toBeInTheDocument()

    await user.keyboard('{ArrowRight}')
    expect(within(dialog).getByText('second.png')).toBeInTheDocument()
    expect(within(dialog).getByText(/2 of 2/)).toBeInTheDocument()

    // Wraps, rather than dead-ending with no indication why the key stopped
    // working.
    await user.keyboard('{ArrowRight}')
    expect(within(dialog).getByText('first.png')).toBeInTheDocument()
  })

  it('closes on Escape', async () => {
    renderInThread([attachment()])
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: /view photo\.png/i }))
    await screen.findByRole('dialog')

    await user.keyboard('{Escape}')

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('offers download and open-in-new-tab from the viewer', async () => {
    renderInThread([attachment()])
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: /view photo\.png/i }))
    const dialog = within(await screen.findByRole('dialog'))

    expect(dialog.getByRole('link', { name: /open in a new tab/i })).toBeInTheDocument()
    await user.click(dialog.getByRole('button', { name: /download photo\.png/i }))

    expect(downloadAttachment).toHaveBeenCalled()
  })

  it('hides the arrows when there is only one attachment', async () => {
    renderInThread([attachment()])
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: /view photo\.png/i }))
    const dialog = within(await screen.findByRole('dialog'))

    expect(dialog.queryByRole('button', { name: /next attachment/i })).not.toBeInTheDocument()
  })

  it('does not put documents in the viewer', async () => {
    // → landing on a spreadsheet in the middle of a set of photos would be
    // nonsense: there is nothing to look at.
    renderInThread([attachment(), DOCUMENT])
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: /view photo\.png/i }))
    const dialog = within(await screen.findByRole('dialog'))

    expect(dialog.queryByText(/1 of 2/)).not.toBeInTheDocument()
    expect(dialog.queryByRole('button', { name: /next attachment/i })).not.toBeInTheDocument()
  })
})

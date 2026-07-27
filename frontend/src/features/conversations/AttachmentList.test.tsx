import { afterEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { store } from '../../app/store'
import { queryClient } from '../../app/queryClient'
import { loggedOut } from '../auth/authSlice'
import { renderAuthenticated } from '../../test/renderAuthenticated'
import { AttachmentList } from './AttachmentList'
import type { Attachment } from './types'

// Isolated from the real network/blob layer — see ConversationViewPage.test.tsx's
// comment on why: jsdom's Blob doesn't implement `.stream()`, which breaks
// MSW's Response construction for any blob-typed response in this
// environment. Mocking `./api` lets this test verify the actual rendering
// decision (image vs. document, size formatting, download wiring) without
// depending on that broken interop.
vi.mock('./api', () => ({
  fetchAttachmentBlobUrl: vi.fn().mockResolvedValue('blob:mock-image-url'),
  downloadAttachment: vi.fn().mockResolvedValue(undefined),
}))

import { downloadAttachment } from './api'

const IMAGE_ATTACHMENT: Attachment = {
  id: 'att-img',
  filename: 'photo.png',
  content_type: 'image/png',
  size_bytes: 204_800,
  validation_status: 'approved',
  message_id: 'msg-1',
  created_at: '2026-01-01T00:00:00Z',
}

const DOCUMENT_ATTACHMENT: Attachment = {
  id: 'att-doc',
  filename: 'invoice.pdf',
  content_type: 'application/pdf',
  size_bytes: 51_200,
  validation_status: 'approved',
  message_id: 'msg-1',
  created_at: '2026-01-01T00:00:00Z',
}

describe('AttachmentList', () => {
  afterEach(() => {
    store.dispatch(loggedOut())
    queryClient.clear()
  })

  it('renders nothing for an empty attachment list', () => {
    const { container } = renderAuthenticated(
      <AttachmentList conversationId="conv-1" attachments={[]} />,
    )
    expect(container).toBeEmptyDOMElement()
  })

  it('renders an image attachment as a clickable inline preview', async () => {
    renderAuthenticated(<AttachmentList conversationId="conv-1" attachments={[IMAGE_ATTACHMENT]} />)

    const downloadButton = await screen.findByRole('button', { name: /download photo\.png/i })
    const img = await screen.findByAltText('photo.png')
    expect(img).toHaveAttribute('src', 'blob:mock-image-url')

    await userEvent.setup().click(downloadButton)
    expect(downloadAttachment).toHaveBeenCalledWith('conv-1', IMAGE_ATTACHMENT)
  })

  it('renders a document attachment with filename, size and a download button', async () => {
    renderAuthenticated(
      <AttachmentList conversationId="conv-1" attachments={[DOCUMENT_ATTACHMENT]} />,
    )

    expect(screen.getByText('invoice.pdf')).toBeInTheDocument()
    expect(screen.getByText('50 KB')).toBeInTheDocument()

    const downloadButton = screen.getByRole('button', { name: /download invoice\.pdf/i })
    await userEvent.setup().click(downloadButton)
    expect(downloadAttachment).toHaveBeenCalledWith('conv-1', DOCUMENT_ATTACHMENT)
  })

  it('renders multiple attachments, each with its own controls', async () => {
    renderAuthenticated(
      <AttachmentList
        conversationId="conv-1"
        attachments={[IMAGE_ATTACHMENT, DOCUMENT_ATTACHMENT]}
      />,
    )

    await waitFor(() =>
      expect(screen.getByRole('button', { name: /download photo\.png/i })).toBeInTheDocument(),
    )
    expect(screen.getByRole('button', { name: /download invoice\.pdf/i })).toBeInTheDocument()
  })
})

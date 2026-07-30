import { useCallback, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import {
  GalleryContext,
  type GalleryContextValue,
  type GalleryItem,
} from './galleryContext'
import type { Message } from '../types'

/** Collects every inline attachment in the thread so the lightbox can move
 * between them with the arrow keys.
 *
 * The list is **derived from the messages** rather than registered by each
 * child as it mounts. Registration would order items by render order, which
 * is not conversation order once messages stream in or a page is prepended
 * — and an agent pressing → expecting the next photo would get whichever
 * one happened to mount last. */
export function MediaGalleryProvider({
  messages,
  children,
}: {
  messages: Message[]
  children: ReactNode
}) {
  const [openIndex, setOpenIndex] = useState<number | null>(null)

  const items = useMemo<GalleryItem[]>(
    () =>
      messages.flatMap((message) =>
        message.attachments
          // Documents and files are not part of the gallery: there is
          // nothing to look at, and including them would make → land on a
          // spreadsheet in the middle of a set of photos.
          .filter((attachment) => attachment.inline && attachment.media_url)
          .map((attachment) => ({ attachment, sentAt: message.created_at })),
      ),
    [messages],
  )

  const openAttachment = useCallback(
    (attachmentId: string) => {
      const index = items.findIndex((item) => item.attachment.id === attachmentId)
      if (index >= 0) setOpenIndex(index)
    },
    [items],
  )

  const value = useMemo<GalleryContextValue>(
    () => ({
      items,
      openIndex,
      openAttachment,
      close: () => setOpenIndex(null),
      goTo: (index) => {
        // Wraps, so → at the end returns to the first rather than dead-ending
        // with no indication of why the key stopped working.
        if (items.length === 0) return
        setOpenIndex(((index % items.length) + items.length) % items.length)
      },
    }),
    [items, openIndex, openAttachment],
  )

  return <GalleryContext.Provider value={value}>{children}</GalleryContext.Provider>
}

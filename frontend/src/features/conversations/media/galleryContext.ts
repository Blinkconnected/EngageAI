import { createContext } from 'react'

import type { Attachment } from '../types'

/** One item the lightbox can show, in conversation order. */
export interface GalleryItem {
  attachment: Attachment
  /** Which message it came from, so the lightbox can say when it was sent. */
  sentAt: string
}

export interface GalleryContextValue {
  items: GalleryItem[]
  openIndex: number | null
  openAttachment: (attachmentId: string) => void
  close: () => void
  goTo: (index: number) => void
}

export const GalleryContext = createContext<GalleryContextValue | null>(null)

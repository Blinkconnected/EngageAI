import { useContext } from 'react'

import { GalleryContext, type GalleryContextValue } from './galleryContext'

/** The conversation's media gallery, or null outside a provider.
 *
 * Null rather than throwing, so an attachment rendered somewhere without a
 * gallery — a composer preview, say — degrades to "no lightbox" instead of
 * taking the screen down.
 *
 * Its own file because a module that exports both a component and a hook
 * breaks fast refresh, and losing hot reload in the busiest part of the app
 * is a real daily cost.
 */
export function useMediaGallery(): GalleryContextValue | null {
  return useContext(GalleryContext)
}

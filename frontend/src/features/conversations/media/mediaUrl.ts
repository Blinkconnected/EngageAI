import { API_BASE_URL } from '../../../shared/api/client'

/** Turns the API-relative media path into something an `<img src>` can use.
 *
 * The server returns a path (`/api/v1/conversations/…`) rather than a full
 * URL, because it does not reliably know the public origin behind a proxy —
 * and a hardcoded one breaks the moment the install moves domain. The
 * browser does know, so joining happens here. */
export function absoluteMediaUrl(mediaUrl: string | null): string | null {
  if (!mediaUrl) return null
  if (/^https?:\/\//i.test(mediaUrl)) return mediaUrl

  // API_BASE_URL already ends with the versioned prefix, and the media path
  // includes it too — so take the origin and let the path supply the rest.
  try {
    const base = new URL(API_BASE_URL, window.location.origin)
    return new URL(mediaUrl, base.origin).toString()
  } catch {
    return mediaUrl
  }
}

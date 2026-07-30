import type { Attachment } from '../types'

/** How much space an attachment should occupy in the thread *before* it
 * loads.
 *
 * Reserving the real shape is what stops a conversation reflowing as photos
 * arrive. On a long thread that reflow means an agent loses their place
 * mid-sentence, which is the most noticeable performance defect a chat UI
 * can have and one no amount of loading-spinner polish disguises. */

/** The widest an inline image or video is drawn. Wide enough that a
 * screenshot of an error message is readable; narrow enough that a bubble
 * still reads as a message rather than a page. */
export const MAX_INLINE_WIDTH = 320

/** Tallest inline media, so a portrait phone photo does not occupy the
 * whole thread and push everything else out of view. */
export const MAX_INLINE_HEIGHT = 360

/** What a video reserves before its metadata loads. Phones record 16:9, so
 * reserving the common case means the thread does not jump for it. */
const DEFAULT_VIDEO_RATIO = 16 / 9

/** What an image of unknown dimensions reserves — squarish, because a
 * wrong guess is least jarring when it is closest to average. */
const UNKNOWN_IMAGE_RATIO = 4 / 3

export interface ReservedBox {
  width: number
  height: number
  /** For the CSS `aspect-ratio` property, which keeps the box correct while
   * the container is narrower than `MAX_INLINE_WIDTH` — a phone, or a
   * split-pane layout. A fixed pixel height would be wrong at every width
   * except the one it was computed for. */
  aspectRatio: string
}

export function reservedBoxFor(attachment: Attachment): ReservedBox {
  const ratio =
    attachment.width && attachment.height
      ? attachment.width / attachment.height
      : attachment.kind === 'video'
        ? DEFAULT_VIDEO_RATIO
        : UNKNOWN_IMAGE_RATIO

  // Fit inside both bounds while keeping the aspect ratio: a tall portrait
  // photo is limited by height, a wide screenshot by width.
  let width = MAX_INLINE_WIDTH
  let height = width / ratio
  if (height > MAX_INLINE_HEIGHT) {
    height = MAX_INLINE_HEIGHT
    width = height * ratio
  }

  return {
    width: Math.round(width),
    height: Math.round(height),
    aspectRatio: `${ratio}`,
  }
}

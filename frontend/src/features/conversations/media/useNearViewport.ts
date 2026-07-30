import { useEffect, useRef, useState } from 'react'

/** Whether an element has come close enough to the viewport to be worth
 * loading.
 *
 * The reason media in a long conversation does not cost anything until it
 * is nearly on screen. Previously every image in the thread fetched as soon
 * as it rendered, so opening a conversation with thirty photos meant thirty
 * simultaneous downloads — a stuttering scroll on a desktop and real money
 * on a phone.
 *
 * `rootMargin` is generous on purpose: media starts loading a screen and a
 * half before it is visible, so scrolling at a normal speed reaches an
 * image that has already decoded rather than a placeholder that then pops.
 *
 * Once true it stays true. Unloading media that scrolled away would mean
 * re-downloading it when the agent scrolls back, which is the opposite of
 * the goal. */
export function useNearViewport<T extends HTMLElement>(
  options: { rootMargin?: string } = {},
): [React.RefObject<T | null>, boolean] {
  const ref = useRef<T | null>(null)
  // jsdom and older Safari have no IntersectionObserver. Decided at render
  // rather than in an effect: loading everything is a worse experience but a
  // working one, and it is knowable before the first paint — setting it from
  // an effect would flash empty placeholders and cascade a render.
  const observable = typeof IntersectionObserver !== 'undefined'
  const [isNear, setIsNear] = useState(!observable)

  useEffect(() => {
    if (isNear || !observable) return
    const element = ref.current
    if (!element) return

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setIsNear(true)
          observer.disconnect()
        }
      },
      { rootMargin: options.rootMargin ?? '600px 0px' },
    )
    observer.observe(element)
    return () => observer.disconnect()
  }, [isNear, observable, options.rootMargin])

  return [ref, isNear]
}

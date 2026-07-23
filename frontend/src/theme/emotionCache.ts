import createCache, { type EmotionCache } from '@emotion/cache'
import { prefixer } from 'stylis'
import rtlPlugin from 'stylis-plugin-rtl'
import type { Direction } from './theme'

export function createEmotionCache(direction: Direction): EmotionCache {
  if (direction === 'rtl') {
    return createCache({ key: 'css-rtl', stylisPlugins: [prefixer, rtlPlugin] })
  }
  return createCache({ key: 'css', stylisPlugins: [prefixer] })
}

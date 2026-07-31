import { useTranslation } from 'react-i18next'

/**
 * Resolving the copy the server sends.
 *
 * Its own module because of the fast-refresh rule — a file may not export
 * both components and plain functions — but it earns the separation anyway:
 * this is the single place every translation key from the connector SDK is
 * turned into words, so the fallback behaviour and the flat-key handling are
 * decided once rather than per screen.
 */

/** A key with a readable fallback.
 *
 * The fallback is the key's own last segment, de-camel-cased. It exists for
 * one situation and is worth being deliberate about: a connector shipped
 * ahead of its translations. Rendering `connect.slack.botTokenLabel` in front
 * of a customer is unforgivable; rendering "bot token label" is merely poor —
 * and it is *visibly* poor, so it gets fixed rather than living forever.
 */
/** Segments that say nothing on their own.
 *
 * `connect.slack.name` would otherwise fall back to "Name", which is worse
 * than the raw key — at least the key is obviously broken. Skipping these
 * yields "Slack", which is very nearly right. */
const GENERIC = new Set(['name', 'label', 'title', 'description', 'help', 'key'])

export function readable(key: string | null | undefined): string {
  if (!key) return ''
  const parts = key.split('.').filter(Boolean)
  // The last segment that carries meaning, skipping generic tails.
  const meaningful =
    [...parts].reverse().find((part) => !GENERIC.has(part)) ?? parts[parts.length - 1] ?? key
  return meaningful
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .replace(/[_-]+/g, ' ')
    .replace(/^./, (c) => c.toUpperCase())
}

/** Copy that is allowed to be absent.
 *
 * For prose — a description, a note — a missing translation should render
 * *nothing*. The readable fallback works for a label, where something is
 * better than an empty field, but applied to a description it produces the
 * same words as the name beside it and the card says everything twice.
 * Silence is the honest degradation for optional copy.
 */
export function useOptionalCopy() {
  const { t } = useTranslation('connectSdk')
  return (key: string | null | undefined, params?: Record<string, unknown>) =>
    key ? t(key, { ...params, keySeparator: false, defaultValue: '' }) : ''
}

export function useConnectCopy() {
  const { t } = useTranslation('connectSdk')
  // `keySeparator: false` because the bundle is **flat**: the server sends
  // `connect.email.check.smtp` and `connect.email.check.smtp.title` as two
  // sibling keys, and under i18next's default dot nesting one would have to
  // become an object and swallow the other. Set per call rather than
  // globally — every other namespace in this app is legitimately nested.
  return (key: string | null | undefined, params?: Record<string, unknown>) =>
    key ? t(key, { ...params, keySeparator: false, defaultValue: readable(key) }) : ''
}

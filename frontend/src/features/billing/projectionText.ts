import type { TFunction } from 'i18next'
import type { Projection } from './types'

/**
 * The method's name and derivation, in the reader's language.
 *
 * The server composes both in English so that every surface — dashboard,
 * reminder email, operator console — describes a projection the same way. A
 * customer still has to be able to read it, so the UI translates from the
 * strategy code and falls back to the server's own words for a strategy this
 * build has never heard of. A newer server must add a method, not blank a
 * card.
 *
 * The **effective** strategy is named, never the requested one: telling a
 * customer "Rolling 7-Day Average" when three days were available and the
 * daily average actually ran is a small lie that costs a great deal of trust
 * once noticed.
 */
export function projectionMethod(projection: Projection, t: TFunction): string {
  const strategy = projection.effective_strategy ?? projection.strategy
  return t(`projection.strategy.${strategy}`, { defaultValue: projection.method })
}

export function projectionExplanation(projection: Projection, t: TFunction): string {
  const strategy = projection.effective_strategy ?? projection.strategy
  return t(`projection.explanation.${strategy}`, {
    defaultValue: projection.method_explanation,
  })
}

/** Why there is no projection. Also server-composed, also translated from its
 * code — "come back tomorrow" and "this period has no usage at all" need
 * different words, and a single "unavailable" makes a customer wonder whether
 * something is broken. */
export function projectionUnavailable(projection: Projection, t: TFunction): string | null {
  if (projection.unavailable_reason === null) return null
  return t(`projection.unavailableReason.${projection.unavailable_reason}`, {
    defaultValue: projection.unavailable_explanation ?? '',
  })
}

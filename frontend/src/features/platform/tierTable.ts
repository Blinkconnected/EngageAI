import type { Tier } from './types'

/**
 * A starting table for an operator switching a flat rate to a tiered one.
 *
 * One open-ended step carrying the rate they already had, so switching model
 * changes the *shape* without silently changing the price. Anything else
 * would mean picking "tiered" quietly repriced the metric.
 *
 * Its own module rather than living beside the editor component: this repo's
 * lint rule forbids a file exporting both a component and a plain function,
 * because mixing them breaks fast refresh.
 */
export function tableFrom(unitAmount: string): Tier[] {
  return [{ up_to: null, unit_amount: unitAmount }]
}

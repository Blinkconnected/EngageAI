import type { TFunction } from 'i18next'

/**
 * What to call a billable metric on screen.
 *
 * The API sends `display_name` as English prose and `metric_code` as a stable
 * identifier. Translating from the code — with the server's own words as the
 * fallback — means an Arabic operator reads Arabic, while a metric declared
 * server-side before anyone has translated it still reads as English rather
 * than as a missing-key placeholder.
 *
 * Its own module rather than a function beside a component: the pricing table,
 * the editor's title, the company billing page and the coverage warning must
 * all call a metric the same thing, and four copies of one `t()` call is how
 * they stop agreeing.
 */
export function metricName(
  t: TFunction,
  metric: { metric_code?: string; code?: string; display_name: string },
): string {
  const code = metric.metric_code ?? metric.code
  return code ? t(`BillableMetrics.${code}`, metric.display_name) : metric.display_name
}

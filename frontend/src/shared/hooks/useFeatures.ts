import { useCurrentUserQuery } from '../../features/session/api'

/**
 * Which product features this company is entitled to, as decided by a
 * platform administrator (their plan, or a per-company override).
 *
 * Deliberately shaped like `usePermissions`, but answering a different
 * question: a permission is "may this *user* do it?", a feature is "has
 * this *company* bought it?". A user can hold every permission in the
 * catalog and still not have a feature.
 *
 * **Defaults to enabled while the profile is loading.** The server is
 * the enforcement point (it answers 402), so an optimistic client only
 * risks briefly showing a link that then explains itself. Defaulting the
 * other way would blank out the navigation on every page load.
 */
export function useFeatures() {
  const { data, isPending } = useCurrentUserQuery()
  const features = data?.features

  return {
    features: features ?? [],
    hasFeature: (key: string) => (features === undefined ? isPending : features.includes(key)),
  }
}

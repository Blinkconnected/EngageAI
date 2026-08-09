/** Shapes the Learning Platform's operator surface returns.
 *
 * Mirrors `backend/src/blinkengage/api/schemas/learning.py`. Deliberately
 * permissive about the shadow payload: it is a diagnostic surface whose
 * questions change as the pilot answers them, and typing every branch of
 * it here would make each new measurement a frontend change too.
 */

/** A number the backend declined to compute, with the reason.
 *
 * `null` is load-bearing on this screen: it means "nothing to measure",
 * which is a different state from zero. Rendering it as 0 would report
 * churn on an installation whose clusters simply have not settled yet.
 */
export type Measured = number | null

export interface ShadowMode {
  active: boolean
  emits_candidates: boolean
  writes_memory: boolean
  creates_knowledge_suggestions: boolean
  publishes_events: boolean
  calls_models: boolean
  note: string
}

export interface Throughput {
  observations_total: number
  by_state: Record<string, number>
  eligible: number
  eligible_fraction: Measured
  observations_per_hour_mean: number
  observations_per_day_mean: number
}

export interface SizeDistribution {
  buckets: Record<string, number>
  total: number
  median: Measured
  p90: Measured
  largest: Measured
  note?: string
}

export interface RunSummary {
  last_started_at: string
  duration_seconds: Measured
  lag_seconds: number
  items_in: number
  items_out: number
  errors: number
  status: string
}

export interface ShadowMetrics {
  measured_at: string
  window_days: number
  algorithm_version: number
  pipeline_version: number
  shadow_mode: ShadowMode
  throughput: Throughput
  growth: {
    clusters_total: number
    created_per_day: Record<string, number>
    created_in_window: number
  }
  size_distribution: SizeDistribution
  stability: { mean: Measured; clusters_measured: number; note: string }
  merge_rate: { merged_clusters: number; total_clusters: number; rate: Measured; note: string }
  duplicate_suppression: {
    observations_eligible: number
    observations_clustered: number
    clustered_fraction: Measured
    note: string
  }
  replay: {
    superseded_generations: number
    observations_total: number
    replay_rate: Measured
    note: string
  }
  trend_quality: {
    confirmed_by_kind: Record<string, number>
    confirmed_total: number
    provisional_total: number
    confirmation_rate: Measured
    precision: Measured
    precision_note: string
  }
  anomaly_quality: {
    by_kind: Record<string, number>
    total: number
    precision: Measured
    precision_note: string
  }
  churn: {
    live_clusters: number
    dormant: number
    archived: number
    singletons: number
    singleton_rate: Measured
    mean_size: Measured
    largest: Measured
    note: string
  }
  processing: {
    runs_recorded: number
    by_run_type: Record<string, RunSummary>
    errors_recent: number
  }
  resource_usage: { measured_here: boolean; see: string }
  floors: Record<string, number>
}

export interface UnclusteredObservation {
  observation_id: string
  observed_at: string
  topics: string[]
  entities: string[]
  reason: string
}

export interface LearningThresholds {
  thresholds: Record<string, number>
  platform_defaults: Record<string, number>
  overridden: string[]
  bounds: Record<string, { min: number; max: number }>
}

export interface ThresholdUpdateResult {
  thresholds: Record<string, number>
  changes: { threshold: string; previous: number; current: number }[]
  clusters_built_under_previous_thresholds: number
}

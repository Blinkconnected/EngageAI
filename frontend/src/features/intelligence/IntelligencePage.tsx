import { Alert, Box, Card, CardContent, Chip, Grid, Stack, Typography } from '@mui/material'
import VisibilityOutlinedIcon from '@mui/icons-material/VisibilityOutlined'
import { useTranslation } from 'react-i18next'
import { usePermissions } from '../../shared/hooks/usePermissions'
import { useShadowMetrics, useUnclustered } from './api'
import { MetricTile } from './MetricTile'
import { SizeDistributionChart } from './SizeDistributionChart'
import { ThresholdPanel } from './ThresholdPanel'

/** The production-pilot dashboard.
 *
 * One question, asked twelve ways: *is the pattern detection worth
 * turning on?* The layout follows the order somebody actually asks it —
 * is it running, is it seeing anything, is what it found any good, and
 * only then the dials.
 *
 * The shadow banner is first and unmissable because it is the fact that
 * makes every other number safe to look at: nothing here is acting on
 * what it shows.
 */
export function IntelligencePage() {
  const { t } = useTranslation('intelligence')
  const { hasPermission } = usePermissions()
  const { data, isLoading, isError } = useShadowMetrics()
  const { data: unclustered } = useUnclustered(50, Boolean(data))

  if (isLoading) {
    return <Typography sx={{ p: 3 }}>{t('Page.loading')}</Typography>
  }
  if (isError || !data) {
    return (
      <Alert severity="error" sx={{ m: 3 }}>
        {t('Page.loadFailed')}
      </Alert>
    )
  }

  const cluster = data.processing.by_run_type.cluster
  const analysis = data.processing.by_run_type.analysis
  const singletonRate = data.churn.singleton_rate

  return (
    <Box sx={{ p: 3 }}>
      <Typography variant="h5" gutterBottom>
        {t('Page.title')}
      </Typography>

      <Alert icon={<VisibilityOutlinedIcon fontSize="inherit" />} severity="info" sx={{ mb: 3 }}>
        <Typography variant="body2" fontWeight={600}>
          {t('Page.shadowBannerTitle')}
        </Typography>
        <Typography variant="body2">{t('Page.shadowBannerBody')}</Typography>
      </Alert>

      {/* --- is it running? ------------------------------------------ */}
      <Typography variant="subtitle2" color="text.secondary" gutterBottom>
        {t('Page.sectionRunning')}
      </Typography>
      <Grid container spacing={2} sx={{ mb: 3 }}>
        <Grid size={{ xs: 6, md: 3 }}>
          <MetricTile
            label={t('Metrics.clusterLatency')}
            value={cluster ? Number((cluster.duration_seconds ?? 0) * 1000).toFixed(0) : null}
            suffix="ms"
            hint={t('Metrics.clusterLatencyHint')}
          />
        </Grid>
        <Grid size={{ xs: 6, md: 3 }}>
          <MetricTile
            label={t('Metrics.queueLag')}
            value={cluster ? Math.round(cluster.lag_seconds / 60) : null}
            suffix={t('Metrics.minutes')}
            hint={t('Metrics.queueLagHint')}
            emphasis={cluster && cluster.lag_seconds > 7200 ? 'warn' : 'none'}
          />
        </Grid>
        <Grid size={{ xs: 6, md: 3 }}>
          <MetricTile
            label={t('Metrics.runErrors')}
            value={data.processing.errors_recent}
            hint={t('Metrics.runErrorsHint')}
            emphasis={data.processing.errors_recent > 0 ? 'warn' : 'good'}
          />
        </Grid>
        <Grid size={{ xs: 6, md: 3 }}>
          <MetricTile
            label={t('Metrics.analysisLatency')}
            value={analysis ? Number((analysis.duration_seconds ?? 0) * 1000).toFixed(0) : null}
            suffix="ms"
          />
        </Grid>
      </Grid>

      {/* --- is it seeing anything? ---------------------------------- */}
      <Typography variant="subtitle2" color="text.secondary" gutterBottom>
        {t('Page.sectionSeeing')}
      </Typography>
      <Grid container spacing={2} sx={{ mb: 3 }}>
        <Grid size={{ xs: 6, md: 3 }}>
          <MetricTile
            label={t('Metrics.observations')}
            value={data.throughput.observations_total}
            hint={t('Metrics.observationsHint')}
          />
        </Grid>
        <Grid size={{ xs: 6, md: 3 }}>
          <MetricTile
            label={t('Metrics.eligible')}
            value={data.throughput.eligible}
            hint={t('Metrics.eligibleHint')}
          />
        </Grid>
        <Grid size={{ xs: 6, md: 3 }}>
          <MetricTile
            label={t('Metrics.perDay')}
            value={data.throughput.observations_per_day_mean}
            hint={t('Metrics.perDayHint')}
          />
        </Grid>
        <Grid size={{ xs: 6, md: 3 }}>
          <MetricTile
            label={t('Metrics.replayRate')}
            value={data.replay.superseded_generations}
            hint={t('Metrics.replayRateHint')}
          />
        </Grid>
      </Grid>

      {/* --- is what it found any good? ------------------------------ */}
      <Typography variant="subtitle2" color="text.secondary" gutterBottom>
        {t('Page.sectionQuality')}
      </Typography>
      <Grid container spacing={2} sx={{ mb: 2 }}>
        <Grid size={{ xs: 6, md: 3 }}>
          <MetricTile
            label={t('Metrics.clusters')}
            value={data.growth.clusters_total}
            hint={t('Metrics.clustersHint')}
          />
        </Grid>
        <Grid size={{ xs: 6, md: 3 }}>
          <MetricTile
            label={t('Metrics.growth')}
            value={data.growth.created_in_window}
            suffix={t('Metrics.inWindow', { days: data.window_days })}
          />
        </Grid>
        <Grid size={{ xs: 6, md: 3 }}>
          <MetricTile
            label={t('Metrics.stability')}
            value={data.stability.mean}
            hint={data.stability.note}
          />
        </Grid>
        <Grid size={{ xs: 6, md: 3 }}>
          <MetricTile
            label={t('Metrics.mergeRate')}
            value={data.merge_rate.rate}
            hint={data.merge_rate.note}
          />
        </Grid>
        <Grid size={{ xs: 6, md: 3 }}>
          <MetricTile
            label={t('Metrics.singletonRate')}
            value={singletonRate}
            hint={data.churn.note}
            // The clearest threshold signal on the page. Above 0.30 the
            // join threshold is grouping too little to be useful.
            emphasis={singletonRate !== null && singletonRate > 0.3 ? 'warn' : 'none'}
          />
        </Grid>
        <Grid size={{ xs: 6, md: 3 }}>
          <MetricTile
            label={t('Metrics.clusteredFraction')}
            value={data.duplicate_suppression.clustered_fraction}
            hint={t('Metrics.clusteredFractionHint')}
          />
        </Grid>
        <Grid size={{ xs: 6, md: 3 }}>
          <MetricTile
            label={t('Metrics.unclustered')}
            value={unclustered ? unclustered.length : null}
            hint={t('Metrics.unclusteredHint')}
          />
        </Grid>
        <Grid size={{ xs: 6, md: 3 }}>
          <MetricTile
            label={t('Metrics.duplicates')}
            value={0}
            hint={data.duplicate_suppression.note}
            emphasis="good"
          />
        </Grid>
      </Grid>

      <Grid container spacing={2} sx={{ mb: 3 }}>
        <Grid size={{ xs: 12, md: 6 }}>
          <SizeDistributionChart data={data.size_distribution} />
        </Grid>
        <Grid size={{ xs: 12, md: 6 }}>
          <Stack spacing={2}>
            <ThresholdPanel canManage={hasPermission('intelligence.manage')} />
            <Card variant="outlined">
              <CardContent>
                <Typography variant="subtitle2" gutterBottom>
                  {t('Findings.title')}
                </Typography>
                <Stack direction="row" spacing={1} sx={{ mb: 1 }}>
                  <Chip
                    size="small"
                    label={t('Findings.trends', { count: data.trend_quality.confirmed_total })}
                  />
                  <Chip
                    size="small"
                    label={t('Findings.anomalies', { count: data.anomaly_quality.total })}
                  />
                </Stack>
                {/* Precision is null by construction in shadow mode, and
                    saying so is more useful than an empty chart. */}
                <Typography variant="caption" color="text.secondary">
                  {data.trend_quality.precision_note}
                </Typography>
              </CardContent>
            </Card>
          </Stack>
        </Grid>
      </Grid>

      <Typography variant="caption" color="text.secondary">
        {t('Page.footer', {
          algorithm: data.algorithm_version,
          pipeline: data.pipeline_version,
          measured: new Date(data.measured_at).toLocaleString(),
        })}
      </Typography>
    </Box>
  )
}

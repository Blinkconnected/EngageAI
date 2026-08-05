/**
 * The distinction the whole pilot dashboard rests on: a number the
 * platform cannot compute is not zero.
 *
 * An operator reads this page to decide whether pattern detection is
 * worth turning on. "Stability: 0" says the clusters are churning —
 * something is wrong. "Stability: —" says nothing has settled yet, which
 * on a new installation is exactly what should be true. Rendering the
 * second as the first would send somebody to investigate a fault that
 * does not exist, and the tile is where that distinction lives.
 */
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { I18nextProvider } from 'react-i18next'
import i18n from '../../i18n'
import { MetricTile } from './MetricTile'
import { SizeDistributionChart } from './SizeDistributionChart'

function renderTile(props: Parameters<typeof MetricTile>[0]) {
  return render(
    <I18nextProvider i18n={i18n}>
      <MetricTile {...props} />
    </I18nextProvider>,
  )
}

describe('MetricTile', () => {
  it('shows an em dash rather than zero when a metric cannot be computed', () => {
    renderTile({ label: 'Stability', value: null })
    expect(screen.getByText('—')).toBeInTheDocument()
    expect(screen.queryByText('0')).not.toBeInTheDocument()
  })

  it('shows a real zero as zero', () => {
    // The other half of the same property: zero is a measurement, and
    // hiding it behind the same dash would be the opposite error.
    renderTile({ label: 'Run errors', value: 0 })
    expect(screen.getByText('0')).toBeInTheDocument()
  })

  it('renders a measured value with its unit', () => {
    renderTile({ label: 'Grouping run', value: 86, suffix: 'ms' })
    expect(screen.getByText('86')).toBeInTheDocument()
    expect(screen.getByText('ms')).toBeInTheDocument()
  })
})

describe('SizeDistributionChart', () => {
  it('says so plainly when there are no groups', () => {
    render(
      <I18nextProvider i18n={i18n}>
        <SizeDistributionChart
          data={{ buckets: {}, total: 0, median: null, p90: null, largest: null }}
        />
      </I18nextProvider>,
    )
    expect(screen.getByText(/no groups yet/i)).toBeInTheDocument()
  })

  it('shows every bucket, including the empty ones', () => {
    // Empty buckets are the signal. A distribution rendered with only
    // its non-zero bars hides the shape — and the shape is the whole
    // reason to show a distribution rather than a mean.
    render(
      <I18nextProvider i18n={i18n}>
        <SizeDistributionChart
          data={{
            buckets: { '1': 12, '2': 0, '3-5': 4, '6-10': 0, '11-25': 1, '26-100': 0, '100+': 0 },
            total: 17,
            median: 1,
            p90: 5,
            largest: 20,
          }}
        />
      </I18nextProvider>,
    )
    expect(screen.getByText('1 conversations')).toBeInTheDocument()
    expect(screen.getByText('100+ conversations')).toBeInTheDocument()
    expect(screen.getByText(/median 1/i)).toBeInTheDocument()
  })
})

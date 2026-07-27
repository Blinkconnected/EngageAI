import { useTranslation } from 'react-i18next'
import { Button, ButtonGroup, Stack, TextField } from '@mui/material'
import { daysAgo, isoDate } from './dateRange'
import type { DateRange } from './types'

const PRESETS: { labelKey: 'preset7d' | 'preset30d' | 'preset90d'; days: number }[] = [
  { labelKey: 'preset7d', days: 6 },
  { labelKey: 'preset30d', days: 29 },
  { labelKey: 'preset90d', days: 89 },
]

interface DateRangeFilterProps {
  range: DateRange
  onChange: (range: DateRange) => void
}

export function DateRangeFilter({ range, onChange }: DateRangeFilterProps) {
  const { t } = useTranslation('reportsCore')
  const invalid = range.date_from > range.date_to

  return (
    <Stack
      direction={{ xs: 'column', sm: 'row' }}
      spacing={1.5}
      sx={{ alignItems: { sm: 'center' }, mb: 3 }}
    >
      <TextField
        label={t('DateRangeFilter.fromLabel')}
        type="date"
        size="small"
        value={range.date_from}
        onChange={(event) => onChange({ ...range, date_from: event.target.value })}
        slotProps={{ inputLabel: { shrink: true } }}
        error={invalid}
      />
      <TextField
        label={t('DateRangeFilter.toLabel')}
        type="date"
        size="small"
        value={range.date_to}
        onChange={(event) => onChange({ ...range, date_to: event.target.value })}
        slotProps={{ inputLabel: { shrink: true } }}
        error={invalid}
        helperText={invalid ? t('DateRangeFilter.fromToHelperText') : undefined}
      />
      <ButtonGroup
        size="small"
        variant="outlined"
        aria-label={t('DateRangeFilter.quickPresetsAriaLabel')}
      >
        {PRESETS.map((preset) => {
          const isActive =
            range.date_to === isoDate(daysAgo(0)) &&
            range.date_from === isoDate(daysAgo(preset.days))
          return (
            <Button
              key={preset.labelKey}
              variant={isActive ? 'contained' : 'outlined'}
              aria-pressed={isActive}
              onClick={() =>
                onChange({ date_from: isoDate(daysAgo(preset.days)), date_to: isoDate(daysAgo(0)) })
              }
            >
              {t(`DateRangeFilter.${preset.labelKey}`)}
            </Button>
          )
        })}
      </ButtonGroup>
    </Stack>
  )
}

import { Button, ButtonGroup, Stack, TextField } from '@mui/material'
import { daysAgo, isoDate } from './dateRange'
import type { DateRange } from './types'

const PRESETS: { label: string; days: number }[] = [
  { label: '7d', days: 6 },
  { label: '30d', days: 29 },
  { label: '90d', days: 89 },
]

interface DateRangeFilterProps {
  range: DateRange
  onChange: (range: DateRange) => void
}

export function DateRangeFilter({ range, onChange }: DateRangeFilterProps) {
  const invalid = range.date_from > range.date_to

  return (
    <Stack
      direction={{ xs: 'column', sm: 'row' }}
      spacing={1.5}
      sx={{ alignItems: { sm: 'center' }, mb: 3 }}
    >
      <TextField
        label="From"
        type="date"
        size="small"
        value={range.date_from}
        onChange={(event) => onChange({ ...range, date_from: event.target.value })}
        slotProps={{ inputLabel: { shrink: true } }}
        error={invalid}
      />
      <TextField
        label="To"
        type="date"
        size="small"
        value={range.date_to}
        onChange={(event) => onChange({ ...range, date_to: event.target.value })}
        slotProps={{ inputLabel: { shrink: true } }}
        error={invalid}
        helperText={invalid ? '"From" must be on or before "To".' : undefined}
      />
      <ButtonGroup size="small" variant="outlined" aria-label="Quick date range presets">
        {PRESETS.map((preset) => (
          <Button
            key={preset.label}
            onClick={() => onChange({ date_from: isoDate(daysAgo(preset.days)), date_to: isoDate(daysAgo(0)) })}
          >
            {preset.label}
          </Button>
        ))}
      </ButtonGroup>
    </Stack>
  )
}

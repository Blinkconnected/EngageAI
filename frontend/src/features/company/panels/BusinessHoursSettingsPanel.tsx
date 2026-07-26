import { useState } from 'react'
import {
  Alert,
  Button,
  Card,
  CardContent,
  Checkbox,
  FormControlLabel,
  Stack,
  Switch,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from '@mui/material'
import { extractErrorMessage } from '../../../shared/api/errors'
import { useUpdateCompanyMutation } from '../api'
import { WEEKDAYS, type BusinessHoursDay, type Company, type Weekday } from '../types'

const DAY_LABELS: Record<Weekday, string> = {
  monday: 'Monday',
  tuesday: 'Tuesday',
  wednesday: 'Wednesday',
  thursday: 'Thursday',
  friday: 'Friday',
  saturday: 'Saturday',
  sunday: 'Sunday',
}

const DEFAULT_DAY: BusinessHoursDay = { open: '09:00', close: '17:00', closed: false }

function fullWeekSchedule(
  schedule: Partial<Record<Weekday, BusinessHoursDay>> | undefined,
): Record<Weekday, BusinessHoursDay> {
  const result = {} as Record<Weekday, BusinessHoursDay>
  for (const day of WEEKDAYS) {
    result[day] = schedule?.[day] ?? { ...DEFAULT_DAY, closed: day === 'saturday' || day === 'sunday' }
  }
  return result
}

export function BusinessHoursSettingsPanel({ company }: { company: Company }) {
  const [enabled, setEnabled] = useState(company.settings.business_hours?.enabled ?? false)
  const [schedule, setSchedule] = useState(() =>
    fullWeekSchedule(company.settings.business_hours?.schedule),
  )
  const updateMutation = useUpdateCompanyMutation()

  function updateDay(day: Weekday, patch: Partial<BusinessHoursDay>) {
    setSchedule((current) => ({ ...current, [day]: { ...current[day], ...patch } }))
  }

  function handleSave() {
    updateMutation.mutate({ settings: { business_hours: { enabled, schedule } } })
  }

  return (
    <Card variant="outlined" sx={{ maxWidth: 640 }}>
      <CardContent>
        <Stack spacing={2}>
          <Typography variant="body2" color="text.secondary">
            When your team is available. Displayed to customers and reserved for future SLA/
            routing use.
          </Typography>

          {updateMutation.isError && (
            <Alert severity="error">{extractErrorMessage(updateMutation.error)}</Alert>
          )}
          {updateMutation.isSuccess && <Alert severity="success">Saved.</Alert>}

          <FormControlLabel
            control={
              <Switch checked={enabled} onChange={(event) => setEnabled(event.target.checked)} />
            }
            label="Enable business hours"
          />

          {enabled && (
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Day</TableCell>
                  <TableCell>Closed</TableCell>
                  <TableCell>Open</TableCell>
                  <TableCell>Close</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {WEEKDAYS.map((day) => {
                  const dayValue = schedule[day]
                  return (
                    <TableRow key={day}>
                      <TableCell>{DAY_LABELS[day]}</TableCell>
                      <TableCell>
                        <Checkbox
                          size="small"
                          checked={dayValue.closed}
                          onChange={(event) => updateDay(day, { closed: event.target.checked })}
                          slotProps={{ input: { 'aria-label': `${DAY_LABELS[day]} closed` } }}
                        />
                      </TableCell>
                      <TableCell>
                        <TextField
                          type="time"
                          size="small"
                          value={dayValue.open}
                          disabled={dayValue.closed}
                          onChange={(event) => updateDay(day, { open: event.target.value })}
                          slotProps={{ htmlInput: { 'aria-label': `${DAY_LABELS[day]} opens at` } }}
                        />
                      </TableCell>
                      <TableCell>
                        <TextField
                          type="time"
                          size="small"
                          value={dayValue.close}
                          disabled={dayValue.closed}
                          onChange={(event) => updateDay(day, { close: event.target.value })}
                          slotProps={{ htmlInput: { 'aria-label': `${DAY_LABELS[day]} closes at` } }}
                        />
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          )}

          <Button
            variant="contained"
            disabled={updateMutation.isPending}
            onClick={handleSave}
            sx={{ alignSelf: 'flex-start' }}
          >
            {updateMutation.isPending ? 'Saving…' : 'Save changes'}
          </Button>
        </Stack>
      </CardContent>
    </Card>
  )
}

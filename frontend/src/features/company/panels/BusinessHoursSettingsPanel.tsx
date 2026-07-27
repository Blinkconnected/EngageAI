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
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from '@mui/material'
import { useTranslation } from 'react-i18next'
import { extractErrorMessage } from '../../../shared/api/errors'
import { useUpdateCompanyMutation } from '../api'
import { WEEKDAYS, type BusinessHoursDay, type Company, type Weekday } from '../types'

const DEFAULT_DAY: BusinessHoursDay = { open: '09:00', close: '17:00', closed: false }

function fullWeekSchedule(
  schedule: Partial<Record<Weekday, BusinessHoursDay>> | undefined,
): Record<Weekday, BusinessHoursDay> {
  const result = {} as Record<Weekday, BusinessHoursDay>
  for (const day of WEEKDAYS) {
    result[day] = schedule?.[day] ?? {
      ...DEFAULT_DAY,
      closed: day === 'saturday' || day === 'sunday',
    }
  }
  return result
}

export function BusinessHoursSettingsPanel({ company }: { company: Company }) {
  const { t } = useTranslation('companySettingsExtra')
  const [enabled, setEnabled] = useState(company.settings.business_hours?.enabled ?? false)
  const [schedule, setSchedule] = useState(() =>
    fullWeekSchedule(company.settings.business_hours?.schedule),
  )
  const updateMutation = useUpdateCompanyMutation()

  const dayLabels: Record<Weekday, string> = {
    monday: t('BusinessHoursSettingsPanel.days.monday'),
    tuesday: t('BusinessHoursSettingsPanel.days.tuesday'),
    wednesday: t('BusinessHoursSettingsPanel.days.wednesday'),
    thursday: t('BusinessHoursSettingsPanel.days.thursday'),
    friday: t('BusinessHoursSettingsPanel.days.friday'),
    saturday: t('BusinessHoursSettingsPanel.days.saturday'),
    sunday: t('BusinessHoursSettingsPanel.days.sunday'),
  }

  const savedEnabled = company.settings.business_hours?.enabled ?? false
  const savedSchedule = fullWeekSchedule(company.settings.business_hours?.schedule)
  const isDirty =
    enabled !== savedEnabled || JSON.stringify(schedule) !== JSON.stringify(savedSchedule)

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
            {t('BusinessHoursSettingsPanel.description')}
          </Typography>

          {updateMutation.isError && (
            <Alert severity="error">{extractErrorMessage(updateMutation.error)}</Alert>
          )}
          {updateMutation.isSuccess && !isDirty && (
            <Alert severity="success">{t('BusinessHoursSettingsPanel.savedAlert')}</Alert>
          )}

          <FormControlLabel
            control={
              <Switch checked={enabled} onChange={(event) => setEnabled(event.target.checked)} />
            }
            label={t('BusinessHoursSettingsPanel.enableBusinessHoursLabel')}
          />

          {enabled && (
            <TableContainer>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>{t('BusinessHoursSettingsPanel.dayColumnHeader')}</TableCell>
                    <TableCell>{t('BusinessHoursSettingsPanel.closedColumnHeader')}</TableCell>
                    <TableCell>{t('BusinessHoursSettingsPanel.openColumnHeader')}</TableCell>
                    <TableCell>{t('BusinessHoursSettingsPanel.closeColumnHeader')}</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {WEEKDAYS.map((day) => {
                    const dayValue = schedule[day]
                    return (
                      <TableRow key={day}>
                        <TableCell>{dayLabels[day]}</TableCell>
                        <TableCell>
                          <Checkbox
                            size="small"
                            checked={dayValue.closed}
                            onChange={(event) => updateDay(day, { closed: event.target.checked })}
                            slotProps={{
                              input: {
                                'aria-label': t('BusinessHoursSettingsPanel.dayClosedAriaLabel', {
                                  day: dayLabels[day],
                                }),
                              },
                            }}
                          />
                        </TableCell>
                        <TableCell>
                          <TextField
                            type="time"
                            size="small"
                            value={dayValue.open}
                            disabled={dayValue.closed}
                            onChange={(event) => updateDay(day, { open: event.target.value })}
                            slotProps={{
                              htmlInput: {
                                'aria-label': t('BusinessHoursSettingsPanel.dayOpensAtAriaLabel', {
                                  day: dayLabels[day],
                                }),
                              },
                            }}
                          />
                        </TableCell>
                        <TableCell>
                          <TextField
                            type="time"
                            size="small"
                            value={dayValue.close}
                            disabled={dayValue.closed}
                            onChange={(event) => updateDay(day, { close: event.target.value })}
                            slotProps={{
                              htmlInput: {
                                'aria-label': t('BusinessHoursSettingsPanel.dayClosesAtAriaLabel', {
                                  day: dayLabels[day],
                                }),
                              },
                            }}
                          />
                        </TableCell>
                      </TableRow>
                    )
                  })}
                </TableBody>
              </Table>
            </TableContainer>
          )}

          <Button
            variant="contained"
            disabled={updateMutation.isPending || !isDirty}
            onClick={handleSave}
            sx={{ alignSelf: 'flex-start' }}
          >
            {updateMutation.isPending
              ? t('BusinessHoursSettingsPanel.savingButton')
              : t('BusinessHoursSettingsPanel.saveButton')}
          </Button>
        </Stack>
      </CardContent>
    </Card>
  )
}

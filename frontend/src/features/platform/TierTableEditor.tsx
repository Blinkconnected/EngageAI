import AddIcon from '@mui/icons-material/Add'
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutlineOutlined'
import {
  Box,
  Button,
  IconButton,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from '@mui/material'
import { useTranslation } from 'react-i18next'
import type { Tier } from './types'

/**
 * The tier table an operator edits.
 *
 * Two rules are enforced by the *shape* of this editor rather than by
 * validation messages, because a rule you cannot break is better than one you
 * are told about after the fact:
 *
 * - **The last step has no bound.** Its "up to" cell is not an input at all,
 *   it reads "and above". A table whose top step ends somewhere leaves a
 *   customer who exceeds it with no price, and the server refuses it — but
 *   the operator should never get far enough to be refused.
 * - **The last step cannot be deleted.** Removing it would leave the same
 *   hole. Every other row has a delete button.
 *
 * Bounds ascending is *not* enforced here: an operator typing a table
 * top-down passes through invalid intermediate states constantly, and a form
 * that fights every keystroke is worse than one that explains itself on save.
 * The server refuses it with the reason, and the preview above stops
 * updating, which is the feedback that actually helps.
 *
 * Amounts are strings throughout — never parsed to a number. A rate of
 * 0.0005 and one of 0.05 are a hundredfold apart, and a float round trip is
 * exactly how the two stop being distinguishable.
 */
export function TierTableEditor({
  tiers,
  onChange,
  unitLabel,
  disabled = false,
}: {
  tiers: Tier[]
  onChange: (tiers: Tier[]) => void
  unitLabel: string
  disabled?: boolean
}) {
  const { t } = useTranslation('platform')

  function update(index: number, patch: Partial<Tier>) {
    onChange(tiers.map((tier, position) => (position === index ? { ...tier, ...patch } : tier)))
  }

  function addStep() {
    // Inserted *before* the open-ended step, never after it: appending would
    // put a bounded step above the unbounded one, which is the one shape the
    // table can never take.
    const head = tiers.slice(0, -1)
    const last = tiers[tiers.length - 1]
    onChange([...head, { up_to: '', unit_amount: last?.unit_amount ?? '' }, last])
  }

  function removeStep(index: number) {
    onChange(tiers.filter((_tier, position) => position !== index))
  }

  return (
    <Box>
      <Table size="small" aria-label={t('PricingEditor.tiersAriaLabel')}>
        <TableHead>
          <TableRow>
            <TableCell sx={{ width: '45%' }}>{t('PricingEditor.tierUpTo')}</TableCell>
            <TableCell>{t('PricingEditor.tierRate')}</TableCell>
            <TableCell padding="none" sx={{ width: 48 }} />
          </TableRow>
        </TableHead>
        <TableBody>
          {tiers.map((tier, index) => {
            const isLast = index === tiers.length - 1
            return (
              <TableRow key={index}>
                <TableCell>
                  {isLast ? (
                    <Typography variant="body2" color="text.secondary">
                      {t('PricingEditor.tierAndAbove')}
                    </Typography>
                  ) : (
                    <TextField
                      size="small"
                      fullWidth
                      value={tier.up_to ?? ''}
                      onChange={(event) => update(index, { up_to: event.target.value })}
                      disabled={disabled}
                      slotProps={{ htmlInput: { inputMode: 'decimal' } }}
                      placeholder="200"
                      label={t('PricingEditor.tierUpToLabel', { unit: unitLabel })}
                    />
                  )}
                </TableCell>
                <TableCell>
                  <TextField
                    size="small"
                    fullWidth
                    value={tier.unit_amount}
                    onChange={(event) => update(index, { unit_amount: event.target.value })}
                    disabled={disabled}
                    slotProps={{ htmlInput: { inputMode: 'decimal' } }}
                    placeholder="0.002"
                    label={t('PricingEditor.tierRateLabel')}
                  />
                </TableCell>
                <TableCell padding="none">
                  {/* The open-ended step has no delete button: removing it
                      would leave a customer past the table with no price. */}
                  {isLast ? null : (
                    <IconButton
                      size="small"
                      onClick={() => removeStep(index)}
                      disabled={disabled}
                      aria-label={t('PricingEditor.removeTier', { position: index + 1 })}
                    >
                      <DeleteOutlineIcon fontSize="small" />
                    </IconButton>
                  )}
                </TableCell>
              </TableRow>
            )
          })}
        </TableBody>
      </Table>

      <Stack direction="row" sx={{ mt: 1, justifyContent: 'space-between', alignItems: 'center' }}>
        <Button size="small" startIcon={<AddIcon />} onClick={addStep} disabled={disabled}>
          {t('PricingEditor.addTier')}
        </Button>
        <Typography variant="caption" color="text.secondary">
          {t('PricingEditor.tierHint')}
        </Typography>
      </Stack>
    </Box>
  )
}

import { useState } from 'react'
import {
  Alert,
  Autocomplete,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Stack,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from '@mui/material'
import { extractErrorMessage } from '../../shared/api/errors'
import { useAllAgentsQuery } from '../agents/api'
import type { Agent } from '../agents/types'
import { useAllDepartmentsQuery } from '../departments/api'
import type { Department } from '../departments/types'
import { useTransferConversationMutation } from './api'
import type { Conversation, TransferTargetType } from './types'

type Step = 'select' | 'confirm'

export function TransferDialog({
  conversation,
  onClose,
}: {
  conversation: Conversation
  onClose: () => void
}) {
  const [step, setStep] = useState<Step>('select')
  const [targetType, setTargetType] = useState<Extract<TransferTargetType, 'agent' | 'department'>>(
    'agent',
  )
  const [selectedAgent, setSelectedAgent] = useState<Agent | null>(null)
  const [selectedDepartment, setSelectedDepartment] = useState<Department | null>(null)
  const [note, setNote] = useState('')

  const agentsQuery = useAllAgentsQuery()
  const departmentsQuery = useAllDepartmentsQuery()
  const transferMutation = useTransferConversationMutation(conversation.id)

  const canContinue = targetType === 'agent' ? Boolean(selectedAgent) : Boolean(selectedDepartment)
  const targetLabel =
    targetType === 'agent' ? (selectedAgent?.full_name ?? '') : (selectedDepartment?.name ?? '')

  function handleClose() {
    transferMutation.reset()
    onClose()
  }

  function handleConfirm() {
    transferMutation.mutate(
      {
        target_type: targetType,
        to_agent_id: targetType === 'agent' ? selectedAgent?.id : undefined,
        to_department_id: targetType === 'department' ? selectedDepartment?.id : undefined,
        note: note.trim() || null,
      },
      { onSuccess: handleClose },
    )
  }

  return (
    <Dialog open onClose={handleClose} fullWidth maxWidth="sm">
      <DialogTitle>Transfer conversation</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          {transferMutation.isError && (
            <Alert severity="error">
              {extractErrorMessage(transferMutation.error, 'Could not transfer this conversation.')}
            </Alert>
          )}

          {step === 'select' ? (
            <>
              <ToggleButtonGroup
                value={targetType}
                exclusive
                fullWidth
                onChange={(_event, value: 'agent' | 'department' | null) => {
                  if (value) setTargetType(value)
                }}
              >
                <ToggleButton value="agent">Agent</ToggleButton>
                <ToggleButton value="department">Department</ToggleButton>
              </ToggleButtonGroup>

              {targetType === 'agent' ? (
                <Autocomplete
                  options={agentsQuery.data ?? []}
                  getOptionLabel={(agent) => agent.full_name}
                  value={selectedAgent}
                  onChange={(_event, value) => setSelectedAgent(value)}
                  loading={agentsQuery.isPending}
                  renderInput={(params) => (
                    <TextField {...params} label="Search agents" autoFocus />
                  )}
                />
              ) : (
                <Autocomplete
                  options={departmentsQuery.data ?? []}
                  getOptionLabel={(department) => department.name}
                  value={selectedDepartment}
                  onChange={(_event, value) => setSelectedDepartment(value)}
                  loading={departmentsQuery.isPending}
                  renderInput={(params) => (
                    <TextField {...params} label="Search departments" autoFocus />
                  )}
                />
              )}

              <TextField
                label="Note (optional)"
                value={note}
                onChange={(event) => setNote(event.target.value)}
                fullWidth
                multiline
                minRows={2}
                helperText="Visible to the recipient and recorded in the transfer history."
              />
            </>
          ) : (
            <Stack spacing={1}>
              <Typography>
                Transfer this conversation to{' '}
                <Typography component="span" sx={{ fontWeight: 600 }}>
                  {targetLabel}
                </Typography>
                {targetType === 'department' ? ' (department)' : ''}?
              </Typography>
              {note.trim() && (
                <Typography variant="body2" color="text.secondary">
                  Note: "{note.trim()}"
                </Typography>
              )}
            </Stack>
          )}
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={handleClose} disabled={transferMutation.isPending}>
          Cancel
        </Button>
        {step === 'select' ? (
          <Button variant="contained" disabled={!canContinue} onClick={() => setStep('confirm')}>
            Continue
          </Button>
        ) : (
          <>
            <Button onClick={() => setStep('select')} disabled={transferMutation.isPending}>
              Back
            </Button>
            <Button
              variant="contained"
              onClick={handleConfirm}
              disabled={transferMutation.isPending}
            >
              {transferMutation.isPending ? 'Transferring…' : 'Confirm transfer'}
            </Button>
          </>
        )}
      </DialogActions>
    </Dialog>
  )
}

import { useState } from 'react'
import { useTranslation } from 'react-i18next'
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
  const { t } = useTranslation('conversationsExtra')
  const [step, setStep] = useState<Step>('select')
  const [targetType, setTargetType] =
    useState<Extract<TransferTargetType, 'agent' | 'department'>>('agent')
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
      <DialogTitle>{t('TransferDialog.title')}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          {transferMutation.isError && (
            <Alert severity="error">
              {extractErrorMessage(
                transferMutation.error,
                t('TransferDialog.transferErrorFallback'),
              )}
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
                <ToggleButton value="agent">{t('TransferDialog.agentToggle')}</ToggleButton>
                <ToggleButton value="department">
                  {t('TransferDialog.departmentToggle')}
                </ToggleButton>
              </ToggleButtonGroup>

              {targetType === 'agent' ? (
                <Autocomplete
                  options={agentsQuery.data ?? []}
                  getOptionLabel={(agent) => agent.full_name}
                  value={selectedAgent}
                  onChange={(_event, value) => setSelectedAgent(value)}
                  loading={agentsQuery.isPending}
                  renderInput={(params) => (
                    <TextField
                      {...params}
                      label={t('TransferDialog.searchAgentsLabel')}
                      autoFocus
                    />
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
                    <TextField
                      {...params}
                      label={t('TransferDialog.searchDepartmentsLabel')}
                      autoFocus
                    />
                  )}
                />
              )}

              <TextField
                label={t('TransferDialog.noteLabel')}
                value={note}
                onChange={(event) => setNote(event.target.value)}
                fullWidth
                multiline
                minRows={2}
                helperText={t('TransferDialog.noteHelperText')}
              />
            </>
          ) : (
            <Stack spacing={1}>
              <Typography>
                {t('TransferDialog.confirmPrefix')}{' '}
                <Typography component="span" sx={{ fontWeight: 600 }}>
                  {targetLabel}
                </Typography>
                {targetType === 'department' ? ` ${t('TransferDialog.departmentSuffix')}` : ''}?
              </Typography>
              {note.trim() && (
                <Typography variant="body2" color="text.secondary">
                  {t('TransferDialog.notePreview', { note: note.trim() })}
                </Typography>
              )}
            </Stack>
          )}
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={handleClose} disabled={transferMutation.isPending}>
          {t('TransferDialog.cancelButton')}
        </Button>
        {step === 'select' ? (
          <Button variant="contained" disabled={!canContinue} onClick={() => setStep('confirm')}>
            {t('TransferDialog.continueButton')}
          </Button>
        ) : (
          <>
            <Button onClick={() => setStep('select')} disabled={transferMutation.isPending}>
              {t('TransferDialog.backButton')}
            </Button>
            <Button
              variant="contained"
              onClick={handleConfirm}
              disabled={transferMutation.isPending}
            >
              {transferMutation.isPending
                ? t('TransferDialog.transferringButton')
                : t('TransferDialog.confirmButton')}
            </Button>
          </>
        )}
      </DialogActions>
    </Dialog>
  )
}

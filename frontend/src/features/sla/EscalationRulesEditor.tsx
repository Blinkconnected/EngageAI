import {
  Autocomplete,
  Box,
  Button,
  IconButton,
  MenuItem,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material'
import { useTranslation } from 'react-i18next'
import AddIcon from '@mui/icons-material/Add'
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutlined'
import { useAllAgentsQuery } from '../agents/api'
import { useAllQueuesQuery } from '../queues/api'
import type { EscalationAction, EscalationRule, EscalationTrigger } from './types'

function emptyRule(): EscalationRule {
  return { trigger: 'breach', action: 'notify', user_ids: [] }
}

export function EscalationRulesEditor({
  rules,
  onChange,
}: {
  rules: EscalationRule[]
  onChange: (next: EscalationRule[]) => void
}) {
  const { t } = useTranslation('sla')
  const queuesQuery = useAllQueuesQuery()
  const agentsQuery = useAllAgentsQuery()

  const TRIGGER_OPTIONS: { value: EscalationTrigger; label: string }[] = [
    { value: 'warning', label: t('EscalationRulesEditor.triggerWarningLabel') },
    { value: 'breach', label: t('EscalationRulesEditor.triggerBreachLabel') },
  ]

  const ACTION_OPTIONS: { value: EscalationAction; label: string }[] = [
    { value: 'reassign_queue', label: t('EscalationRulesEditor.actionReassignQueueLabel') },
    { value: 'reassign_agent', label: t('EscalationRulesEditor.actionReassignAgentLabel') },
    { value: 'notify', label: t('EscalationRulesEditor.actionNotifyLabel') },
  ]

  function updateRule(index: number, patch: Partial<EscalationRule>) {
    onChange(rules.map((rule, i) => (i === index ? { ...rule, ...patch } : rule)))
  }

  function removeRule(index: number) {
    onChange(rules.filter((_, i) => i !== index))
  }

  function addRule() {
    onChange([...rules, emptyRule()])
  }

  return (
    <Stack spacing={2}>
      {/* `component="p"` — subtitle2 defaults to `<h6>`, which would
          otherwise skip straight from the dialog's own `<h2>` title. */}
      <Typography variant="subtitle2" component="p" sx={{ fontWeight: 600 }}>
        {t('EscalationRulesEditor.sectionTitle')}
      </Typography>
      {rules.length === 0 && (
        <Typography variant="body2" color="text.secondary">
          {t('EscalationRulesEditor.emptyDescription')}
        </Typography>
      )}
      {rules.map((rule, index) => (
        <Box
          key={index}
          sx={{
            display: 'flex',
            flexWrap: 'wrap',
            gap: 1.5,
            alignItems: 'flex-start',
            p: 1.5,
            border: '1px solid',
            borderColor: 'divider',
            borderRadius: 1,
          }}
        >
          <TextField
            select
            label={t('EscalationRulesEditor.whenLabel')}
            value={rule.trigger}
            onChange={(event) =>
              updateRule(index, { trigger: event.target.value as EscalationTrigger })
            }
            size="small"
            sx={{ minWidth: { xs: '100%', sm: 200 } }}
          >
            {TRIGGER_OPTIONS.map((option) => (
              <MenuItem key={option.value} value={option.value}>
                {option.label}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            select
            label={t('EscalationRulesEditor.thenLabel')}
            value={rule.action}
            onChange={(event) =>
              updateRule(index, {
                action: event.target.value as EscalationAction,
                target_queue_id: null,
                target_agent_id: null,
                user_ids: [],
              })
            }
            size="small"
            sx={{ minWidth: { xs: '100%', sm: 220 } }}
          >
            {ACTION_OPTIONS.map((option) => (
              <MenuItem key={option.value} value={option.value}>
                {option.label}
              </MenuItem>
            ))}
          </TextField>

          {rule.action === 'reassign_queue' && (
            <TextField
              select
              label={t('EscalationRulesEditor.targetQueueLabel')}
              value={rule.target_queue_id ?? ''}
              disabled={queuesQuery.isPending}
              onChange={(event) => updateRule(index, { target_queue_id: event.target.value })}
              size="small"
              required
              sx={{ minWidth: { xs: '100%', sm: 200 } }}
            >
              {queuesQuery.data?.map((queue) => (
                <MenuItem key={queue.id} value={queue.id}>
                  {queue.name}
                </MenuItem>
              ))}
            </TextField>
          )}

          {rule.action === 'reassign_agent' && (
            <TextField
              select
              label={t('EscalationRulesEditor.targetAgentLabel')}
              value={rule.target_agent_id ?? ''}
              disabled={agentsQuery.isPending}
              onChange={(event) => updateRule(index, { target_agent_id: event.target.value })}
              size="small"
              required
              sx={{ minWidth: { xs: '100%', sm: 200 } }}
            >
              {agentsQuery.data?.map((agent) => (
                <MenuItem key={agent.id} value={agent.user_id}>
                  {agent.full_name}
                </MenuItem>
              ))}
            </TextField>
          )}

          {rule.action === 'notify' && (
            <Autocomplete
              multiple
              size="small"
              sx={{ minWidth: { xs: '100%', sm: 260 } }}
              options={agentsQuery.data ?? []}
              loading={agentsQuery.isPending}
              getOptionLabel={(agent) => agent.full_name}
              isOptionEqualToValue={(option, value) => option.user_id === value.user_id}
              value={(agentsQuery.data ?? []).filter((agent) =>
                (rule.user_ids ?? []).includes(agent.user_id),
              )}
              onChange={(_event, selected) =>
                updateRule(index, { user_ids: selected.map((agent) => agent.user_id) })
              }
              renderInput={(params) => (
                <TextField {...params} label={t('EscalationRulesEditor.notifyLabel')} />
              )}
            />
          )}

          <Tooltip title={t('EscalationRulesEditor.removeRuleTooltip')}>
            <IconButton
              size="small"
              onClick={() => removeRule(index)}
              aria-label={t('EscalationRulesEditor.removeRuleAriaLabel')}
            >
              <DeleteOutlineIcon fontSize="small" />
            </IconButton>
          </Tooltip>
        </Box>
      ))}
      <Button startIcon={<AddIcon />} onClick={addRule} sx={{ alignSelf: 'flex-start' }}>
        {t('EscalationRulesEditor.addRuleButton')}
      </Button>
    </Stack>
  )
}

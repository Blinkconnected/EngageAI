import { useTranslation } from 'react-i18next'
import {
  Alert,
  Button,
  Chip,
  Divider,
  Link,
  MenuItem,
  Rating,
  Stack,
  TextField,
  Typography,
} from '@mui/material'
import { Link as RouterLink } from 'react-router-dom'
import { extractErrorMessage } from '../../shared/api/errors'
import { usePermissions } from '../../shared/hooks/usePermissions'
import { useAllAgentsQuery } from '../agents/api'
import { useAllChannelsQuery } from '../channels/api'
import { useAllDepartmentsQuery } from '../departments/api'
import { useAllQueuesQuery } from '../queues/api'
import { useSummarizeConversationMutation } from './aiApi'
import { useUpdateConversationMutation } from './api'
import { CONVERSATION_STATUSES, type Conversation, type ConversationStatus } from './types'

// Maps each status to the i18n key holding its dropdown label — the label
// itself can't live in this module-scope map since translation requires
// the `t` function, which is only available inside the component.
const STATUS_OPTION_KEY: Record<ConversationStatus, string> = {
  new: 'statusNew',
  waiting: 'statusWaiting',
  in_progress: 'statusInProgress',
  waiting_customer: 'statusWaitingCustomer',
  waiting_agent: 'statusWaitingAgent',
  resolved: 'statusResolved',
  customer_feedback: 'statusCustomerFeedback',
  closed: 'statusClosed',
}

/**
 * The occasional half of a conversation's controls.
 *
 * Ownership — Pick up, Ask AI, Take over, Transfer, Release — used to
 * live here too, which meant the four actions an agent performs all day
 * were behind a menu and a drawer. They are in `ConversationHeaderBar`
 * now, permanently visible, and deliberately not repeated here: the same
 * button in two places is how a screen stops being trustworthy.
 *
 * What stayed is what genuinely is occasional — re-filing the
 * conversation under a different status or queue, and reading the
 * customer, the channel and the AI summary.
 */
export function ConversationSidebar({
  conversation,
  customerName,
  customerRatingAverage,
  customerRatingCount,
}: {
  conversation: Conversation
  customerName: string
  customerRatingAverage: number | null
  customerRatingCount: number
}) {
  const { t } = useTranslation('conversationsCore')
  const { hasPermission } = usePermissions()

  const channelsQuery = useAllChannelsQuery()
  const agentsQuery = useAllAgentsQuery()
  const departmentsQuery = useAllDepartmentsQuery()
  const queuesQuery = useAllQueuesQuery()
  const updateMutation = useUpdateConversationMutation(conversation.id)
  const summaryMutation = useSummarizeConversationMutation()

  const channel = channelsQuery.data?.find((c) => c.id === conversation.channel_config_id)
  const assignedAgent = agentsQuery.data?.find((a) => a.id === conversation.assigned_agent_id)
  const assignedDepartment = departmentsQuery.data?.find((d) => d.id === conversation.department_id)

  return (
    <Stack spacing={2} sx={{ p: 2, width: { xs: '100%', md: 280 }, flexShrink: 0 }}>
      {updateMutation.isError && (
        <Alert severity="error" onClose={() => updateMutation.reset()}>
          {extractErrorMessage(updateMutation.error, t('ConversationSidebar.updateErrorFallback'))}
        </Alert>
      )}

      <div>
        <Typography variant="overline" color="text.secondary">
          {t('ConversationSidebar.customerLabel')}
        </Typography>
        {/* `component="p"` — MUI's default subtitle1 mapping is `<h6>`,
            which (now that ConversationViewPage renders a real `<h1>`
            via PageHeader) would otherwise skip straight from h1 to h6. */}
        <Typography variant="subtitle1" component="p">
          <Link component={RouterLink} to={`/customers/${conversation.customer_id}`}>
            {customerName}
          </Link>
        </Typography>
        {customerRatingCount > 0 && (
          <Stack direction="row" spacing={0.5} sx={{ alignItems: 'center' }}>
            <Rating value={customerRatingAverage} precision={0.5} readOnly size="small" />
            <Typography variant="caption" color="text.secondary">
              {t('ConversationSidebar.customerRatingCount', { count: customerRatingCount })}
            </Typography>
          </Stack>
        )}
      </div>
      <div>
        <Typography variant="overline" color="text.secondary">
          {t('ConversationSidebar.channelLabel')}
        </Typography>
        <Typography variant="body2">
          {channel?.display_name ?? t('ConversationSidebar.emptyValue')}
        </Typography>
      </div>

      {hasPermission('ai.use') && (
        <div>
          <Typography variant="overline" color="text.secondary" sx={{ display: 'block' }}>
            {t('ConversationSidebar.aiSummaryLabel')}
          </Typography>
          {summaryMutation.isError && (
            <Alert
              severity="error"
              sx={{ mt: 0.5, mb: 0.5 }}
              onClose={() => summaryMutation.reset()}
            >
              {extractErrorMessage(
                summaryMutation.error,
                t('ConversationSidebar.summarizeErrorFallback'),
              )}
            </Alert>
          )}
          {summaryMutation.data ? (
            <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap' }}>
              {summaryMutation.data}
            </Typography>
          ) : (
            <Button
              size="small"
              onClick={() => summaryMutation.mutate(conversation.id)}
              disabled={summaryMutation.isPending}
              sx={{ px: 0 }}
            >
              {summaryMutation.isPending
                ? t('ConversationSidebar.summarizingButton')
                : t('ConversationSidebar.generateSummaryButton')}
            </Button>
          )}
        </div>
      )}

      <Divider />

      <TextField
        select
        label={t('ConversationSidebar.statusLabel')}
        size="small"
        value={conversation.status}
        onChange={(event) =>
          updateMutation.mutate({ status: event.target.value as Conversation['status'] })
        }
      >
        {CONVERSATION_STATUSES.map((status) => (
          <MenuItem key={status} value={status}>
            {t(`ConversationSidebar.${STATUS_OPTION_KEY[status]}`)}
          </MenuItem>
        ))}
      </TextField>

      <div>
        <Typography variant="overline" color="text.secondary">
          {t('ConversationSidebar.assignedToLabel')}
        </Typography>
        {conversation.autopilot_active ? (
          <div>
            <Chip label={t('ConversationSidebar.autopilotActiveLabel')} size="small" color="info" />
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>
              {t('ConversationSidebar.autopilotActiveHelperText')}
            </Typography>
          </div>
        ) : (
          <Typography variant="body2">
            {assignedAgent?.full_name ??
              (assignedDepartment
                ? t('ConversationSidebar.departmentSuffixLabel', {
                    departmentName: assignedDepartment.name,
                  })
                : t('ConversationSidebar.unassignedValue'))}
          </Typography>
        )}
      </div>

      <TextField
        select
        label={t('ConversationSidebar.queueLabel')}
        size="small"
        value={conversation.queue_id ?? ''}
        disabled={queuesQuery.isPending}
        onChange={(event) => updateMutation.mutate({ queue_id: event.target.value || null })}
      >
        <MenuItem value="">{t('ConversationSidebar.noQueueOption')}</MenuItem>
        {queuesQuery.data?.map((queue) => (
          <MenuItem key={queue.id} value={queue.id}>
            {queue.name}
          </MenuItem>
        ))}
      </TextField>
    </Stack>
  )
}

import { Alert, Stack } from '@mui/material'
import { ConversationTimeline } from './ConversationTimeline'
import { InspectorCards, SummaryCard } from './InspectorCards'
import { useConversationInspection } from './api'
import { TimelineSkeleton } from './TimelineSkeleton'

/** The Conversation Story, whole.
 *
 * Summary first — what is going on right now. Then the timeline, which is
 * the product: reading it top to bottom should explain the conversation
 * without anybody reconstructing it. The cards below regroup the same facts
 * by subject, collapsed, for the reader who has found their moment and wants
 * the detail around it.
 */
export function ConversationInspector({ conversationId }: { conversationId: string }) {
  const query = useConversationInspection(conversationId)

  if (query.isLoading) {
    return <TimelineSkeleton />
  }

  if (query.isError || !query.data) {
    return (
      <ConversationTimeline
        events={[]}
        error={query.error ?? new Error('unavailable')}
        onRetry={() => void query.refetch()}
      />
    )
  }

  const inspection = query.data

  return (
    <Stack spacing={2}>
      <SummaryCard inspection={inspection} />
      {/* What the platform does not know, said out loud rather than left as
          a blank section — an investigator has to tell "this did not happen"
          from "this was not recorded". */}
      {inspection.gaps.length > 0 ? (
        <Alert severity="info">
          {inspection.gaps.map((gap) => (
            <div key={gap}>{gap}</div>
          ))}
        </Alert>
      ) : null}
      <ConversationTimeline events={inspection.timeline} gaps={inspection.gaps} />
      <InspectorCards inspection={inspection} />
    </Stack>
  )
}

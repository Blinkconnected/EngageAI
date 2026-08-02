import { memo } from 'react'
import { Box, Chip, Stack, Tooltip } from '@mui/material'
import { useTranslation } from 'react-i18next'
import { WORK_QUEUES, type InboxView, type Workload } from './inboxTypes'

/** The queues an agent moves between.
 *
 * Not filters. Switching from *Waiting pickup* to *Breached* should feel like
 * moving from one desk to another — different work, different mindset — not
 * like editing a query. A filter asks "how do you want the data narrowed",
 * which requires knowing the data model before you can ask a question, and
 * puts the framing on the person least able to carry it at 9am.
 *
 * **Counts are part of the label.** "Breached (4)" answers a question before
 * it is clicked; "Breached" invites a click to find out.
 *
 * **Empty queues stay visible**, greyed, showing their zero. "Breached (0)"
 * is one of the most valuable things this screen can say, and hiding it would
 * remove exactly the reassurance a morning needs.
 */
const ICONS: Record<InboxView, string> = {
  active: '📋',
  needs_attention: '🚨',
  waiting_pickup: '📥',
  mine: '👤',
  ai_working: '🤖',
  waiting_customer: '💬',
  at_risk: '⚠️',
  breached: '🔴',
  resolved_today: '✅',
}

export const WorkQueues = memo(function WorkQueues({
  selected,
  workload,
  onSelect,
}: {
  selected: InboxView
  workload: Workload | undefined
  onSelect: (view: InboxView) => void
}) {
  const { t } = useTranslation('conversationsCore')

  return (
    <Stack
      direction="row"
      spacing={1}
      role="tablist"
      aria-label={t('Inbox.queuesAria')}
      sx={{ flexWrap: 'wrap', gap: 1, mb: 2 }}
    >
      {WORK_QUEUES.map((view) => {
        const count = workload?.[view]
        const active = selected === view
        const empty = count === 0
        return (
          <Tooltip key={view} title={t(`Inbox.viewMeaning.${view}`)}>
            <Chip
              role="tab"
              aria-selected={active}
              // Named explicitly. A Tooltip lends its text to the child's
              // accessible name when the child has none of its own, so the
              // queue announced itself as its own definition — a screen
              // reader heard "a target was missed" where sighted users read
              // "Breached (4)". The meaning stays as the tooltip, which is
              // supplementary rather than the label.
              aria-label={`${t(`Inbox.view.${view}`)}${count === undefined ? '' : ` (${count})`}`}
              label={`${ICONS[view]} ${t(`Inbox.view.${view}`)}${
                count === undefined ? '' : ` (${count})`
              }`}
              onClick={() => onSelect(view)}
              color={active ? 'primary' : 'default'}
              variant={active ? 'filled' : 'outlined'}
              sx={{
                // An empty queue is still shown — it is telling the agent
                // something — but it recedes so the ones with work in them
                // are what the eye lands on.
                opacity: empty && !active ? 0.55 : 1,
                fontWeight: active ? 600 : 400,
              }}
            />
          </Tooltip>
        )
      })}
      <Box sx={{ flexGrow: 1 }} />
    </Stack>
  )
})

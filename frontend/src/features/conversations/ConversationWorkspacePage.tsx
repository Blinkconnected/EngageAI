import { useParams, useSearchParams } from 'react-router-dom'
import { Box, useMediaQuery, useTheme } from '@mui/material'
import { ConversationFiltersPanel, type ConversationFilters } from './ConversationFiltersPanel'
import { ConversationListPanel } from './ConversationListPanel'
import { ConversationViewPage } from './ConversationViewPage'
import { DRAWER_WIDTH } from '../layout/AppLayout'
import { CONVERSATION_STATUSES, type ConversationStatus } from './types'

const FILTERS_PANE_WIDTH = 220
const LIST_PANE_WIDTH = 320
const CUSTOMER_PANE_WIDTH = 280
// AppLayout's nav + this workspace's own filters and list panes +
// ConversationSidebar's fixed customer panel = the chrome that never
// shrinks, before the message thread gets anything. `DRAWER_WIDTH` is
// imported rather than repeated: it was hard-coded here as 260, so
// narrowing the sidebar silently left this threshold wrong.
// This is the actual minimum width the message column needs to stay
// usable, not an arbitrary round number.
const MESSAGE_COLUMN_MIN_WIDTH = 400
const FIVE_COLUMN_MIN_WIDTH =
  DRAWER_WIDTH +
  FILTERS_PANE_WIDTH +
  LIST_PANE_WIDTH +
  CUSTOMER_PANE_WIDTH +
  MESSAGE_COLUMN_MIN_WIDTH

function isConversationStatus(value: string | null): value is ConversationStatus {
  return value !== null && (CONVERSATION_STATUSES as readonly string[]).includes(value)
}

/** The five-column conversation workspace:
 *
 * ```
 * | Sidebar | Filters & Queues | Conversation List | Conversation | Customer Details |
 * ```
 *
 * The Sidebar is `AppLayout`'s own nav; the remaining four live here
 * (the last two inside `ConversationViewPage`). Every column owns its
 * own scroll region and the page itself never scrolls — see
 * `docs/architecture/frontend.md`'s "Independent per-column scrolling"
 * section for the rules this implements, and `AppLayout`'s
 * `isFullBleedRoute`, which drops the page gutter and outer scrollbar
 * for this route.
 *
 * Filter state lives in the URL, not local state: this component fully
 * unmounts whenever the agent navigates away and back, which would
 * otherwise silently reset their chosen status/queue every time.
 *
 * Below `FIVE_COLUMN_MIN_WIDTH` there is no room for all five at once,
 * so the filters and list panes drop out and only the open conversation
 * shows — the same master-detail fallback a phone's Mail app uses, with
 * `ConversationViewPage`'s own back button returning to the Inbox.
 */
export function ConversationWorkspacePage() {
  const { conversationId } = useParams<{ conversationId: string }>()
  const theme = useTheme()
  const isDesktop = useMediaQuery(theme.breakpoints.up(FIVE_COLUMN_MIN_WIDTH))
  const [searchParams, setSearchParams] = useSearchParams()

  const statusParam = searchParams.get('status')
  const filters: ConversationFilters = {
    status: isConversationStatus(statusParam) ? statusParam : 'open',
    queueId: searchParams.get('queue'),
  }

  function handleFiltersChange(next: ConversationFilters) {
    setSearchParams(
      (previous) => {
        const params = new URLSearchParams(previous)
        if (next.status === 'open') params.delete('status')
        else params.set('status', next.status)
        if (next.queueId === null) params.delete('queue')
        else params.set('queue', next.queueId)
        return params
      },
      { replace: true },
    )
  }

  return (
    <Box sx={{ display: 'flex', flexGrow: 1, minHeight: 0, overflow: 'hidden' }}>
      {isDesktop && (
        <>
          <Box
            sx={{
              width: FILTERS_PANE_WIDTH,
              flexShrink: 0,
              borderRight: 1,
              borderColor: 'divider',
              minHeight: 0,
            }}
          >
            <ConversationFiltersPanel filters={filters} onChange={handleFiltersChange} />
          </Box>
          <Box
            sx={{
              width: LIST_PANE_WIDTH,
              flexShrink: 0,
              borderRight: 1,
              borderColor: 'divider',
              minHeight: 0,
            }}
          >
            <ConversationListPanel
              selectedConversationId={conversationId}
              status={filters.status}
              queueId={filters.queueId}
            />
          </Box>
        </>
      )}
      <Box
        sx={{
          flexGrow: 1,
          // A genuine floor, not 0 — if this pane ever gets squeezed
          // below what the message thread needs (a resize edge case, a
          // narrower custom breakpoint elsewhere), it should overflow
          // with horizontal scroll rather than silently render 0px wide.
          minWidth: MESSAGE_COLUMN_MIN_WIDTH,
          minHeight: 0,
          height: '100%',
          overflow: 'hidden',
        }}
      >
        <ConversationViewPage />
      </Box>
    </Box>
  )
}

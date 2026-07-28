import { useParams } from 'react-router-dom'
import { Box, useMediaQuery, useTheme } from '@mui/material'
import { ConversationListPanel } from './ConversationListPanel'
import { ConversationViewPage } from './ConversationViewPage'

const LIST_PANE_WIDTH = 320
// AppLayout's nav (260) + this list pane (320) + ConversationSidebar's
// fixed customer panel (280) = 860px of chrome that never shrinks,
// before the message thread gets anything. MUI's stock `md` (900px)
// leaves only 40px for it — this is the actual minimum width the
// message column needs to stay usable (roughly matching the Inbox's own
// tablet-breakpoint reasoning), not an arbitrary round number.
const MESSAGE_COLUMN_MIN_WIDTH = 400
const THREE_PANE_MIN_WIDTH = 260 + LIST_PANE_WIDTH + 280 + MESSAGE_COLUMN_MIN_WIDTH

/** The 3-pane conversation workspace: a persistent conversation list on
 * the left (`ConversationListPanel`), and the open conversation — message
 * thread, composer, and customer info panel — filling the rest
 * (`ConversationViewPage`, unchanged internally). Only the message
 * thread scrolls; the list, composer, and customer panel all stay put —
 * see `AppLayout.tsx`'s `main` region for the height-bounding fix this
 * relies on.
 *
 * Below `THREE_PANE_MIN_WIDTH` there's no room for all three panes at
 * once: only the list shows at `/conversations` (the Inbox page, not
 * this component) and only the conversation shows here at
 * `/conversations/:id`, with `ConversationViewPage`'s own back button
 * returning to the list — the same master-detail pattern a phone's Mail
 * app uses. This used to switch at MUI's stock `md` (900px), which left
 * only 40px for the message column — a real collapse this custom
 * breakpoint fixes, not just a mobile/desktop question anymore. */
export function ConversationWorkspacePage() {
  const { conversationId } = useParams<{ conversationId: string }>()
  const theme = useTheme()
  const isDesktop = useMediaQuery(theme.breakpoints.up(THREE_PANE_MIN_WIDTH))

  return (
    <Box sx={{ display: 'flex', height: '100%', minHeight: 0, overflow: 'hidden' }}>
      {isDesktop && (
        <Box
          sx={{
            width: LIST_PANE_WIDTH,
            flexShrink: 0,
            borderRight: 1,
            borderColor: 'divider',
            minHeight: 0,
          }}
        >
          <ConversationListPanel selectedConversationId={conversationId} />
        </Box>
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

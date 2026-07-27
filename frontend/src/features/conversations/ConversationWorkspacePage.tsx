import { useParams } from 'react-router-dom'
import { Box, useMediaQuery, useTheme } from '@mui/material'
import { ConversationListPanel } from './ConversationListPanel'
import { ConversationViewPage } from './ConversationViewPage'

const LIST_PANE_WIDTH = 320

/** The 3-pane conversation workspace: a persistent conversation list on
 * the left (`ConversationListPanel`), and the open conversation — message
 * thread, composer, and customer info panel — filling the rest
 * (`ConversationViewPage`, unchanged internally). Only the message
 * thread scrolls; the list, composer, and customer panel all stay put —
 * see `AppLayout.tsx`'s `main` region for the height-bounding fix this
 * relies on.
 *
 * On mobile there's no room for both panes at once: only the list shows
 * at `/conversations` (the Inbox page, not this component) and only the
 * conversation shows here at `/conversations/:id`, with
 * `ConversationViewPage`'s own back button returning to the list — the
 * same master-detail pattern a phone's Mail app uses. */
export function ConversationWorkspacePage() {
  const { conversationId } = useParams<{ conversationId: string }>()
  const theme = useTheme()
  const isDesktop = useMediaQuery(theme.breakpoints.up('md'))

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
      <Box sx={{ flexGrow: 1, minWidth: 0, minHeight: 0, height: '100%', overflow: 'hidden' }}>
        <ConversationViewPage />
      </Box>
    </Box>
  )
}

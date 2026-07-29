import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
  Box,
  Drawer,
  IconButton,
  ListItemIcon,
  ListItemText,
  Menu,
  MenuItem,
  Stack,
  Tab,
  Tabs,
  Typography,
} from '@mui/material'
import CloseIcon from '@mui/icons-material/Close'
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined'
import MoreVertIcon from '@mui/icons-material/MoreVert'

/** Wide enough for the status/queue/assignment controls the panel holds
 * without becoming a second workspace. */
const DETAILS_PANEL_WIDTH = 340
import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import { PageHeader } from '../../shared/components/PageHeader'
import { LoadingState } from '../../shared/components/LoadingState'
import { ErrorState } from '../../shared/components/ErrorState'
import { useCustomerQuery } from '../customers/api'
import { useRealtime } from '../realtime/context'
import { useConversationQuery } from './api'
import { ConversationSidebar } from './ConversationSidebar'
import { MessageThread } from './MessageThread'
import { ReplyBox } from './ReplyBox'
import { NotesPanel } from './NotesPanel'
import { TransferHistoryPanel } from './TransferHistoryPanel'

export function ConversationViewPage() {
  const { t } = useTranslation('conversationsCore')
  const { conversationId } = useParams<{ conversationId: string }>()
  const navigate = useNavigate()
  const [tab, setTab] = useState<'messages' | 'notes' | 'transfers'>('messages')
  const [menuAnchor, setMenuAnchor] = useState<HTMLElement | null>(null)
  const [detailsOpen, setDetailsOpen] = useState(false)

  const conversationQuery = useConversationQuery(conversationId)
  const customerQuery = useCustomerQuery(conversationQuery.data?.customer_id)
  const { sendTyping } = useRealtime()

  if (conversationQuery.isPending) {
    return <LoadingState label={t('ConversationViewPage.loadingLabel')} />
  }
  if (conversationQuery.isError) {
    return (
      <ErrorState error={conversationQuery.error} onRetry={() => conversationQuery.refetch()} />
    )
  }

  const conversation = conversationQuery.data

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 }}>
      {/* A fixed workspace header bar, not page content: it supplies its
          own gutter (the workspace runs edge to edge — see AppLayout's
          full-bleed `main`) and never scrolls, so the chat and details
          columns below own the entire remaining height between them. */}
      <Stack
        direction="row"
        spacing={1}
        sx={{
          alignItems: 'flex-start',
          flexShrink: 0,
          px: 2,
          pt: 2,
          pb: 1,
          borderBottom: 1,
          borderColor: 'divider',
        }}
      >
        <IconButton
          onClick={() => navigate('/conversations')}
          aria-label={t('ConversationViewPage.backButtonAriaLabel')}
          sx={{ mt: 0.5 }}
        >
          <ArrowBackIcon />
        </IconButton>
        {/* Reuses the same PageHeader (and therefore the same single `h1`)
            every other page in the app renders its title through — this
            page previously hand-rolled a smaller, non-h1 title. */}
        <Box sx={{ flexGrow: 1 }}>
          <PageHeader
            title={customerQuery.data?.full_name ?? t('ConversationViewPage.defaultTitle')}
          />
        </Box>
        <IconButton
          onClick={(event) => setMenuAnchor(event.currentTarget)}
          aria-label={t('ConversationViewPage.conversationMenuAriaLabel')}
          sx={{ mt: 0.5 }}
        >
          <MoreVertIcon />
        </IconButton>
        <Menu
          anchorEl={menuAnchor}
          open={menuAnchor !== null}
          onClose={() => setMenuAnchor(null)}
        >
          <MenuItem
            onClick={() => {
              setMenuAnchor(null)
              setDetailsOpen(true)
            }}
          >
            <ListItemIcon>
              <InfoOutlinedIcon fontSize="small" />
            </ListItemIcon>
            <ListItemText>{t('ConversationViewPage.conversationDetails')}</ListItemText>
          </MenuItem>
        </Menu>
      </Stack>

      <Stack
        direction={{ xs: 'column', md: 'row' }}
        sx={{
          flexGrow: 1,
          minHeight: 0,
          // No card border/radius/margin: this row runs edge to edge as
          // application chrome. Each column is delimited by the divider
          // rule below, the way Intercom/Zendesk-style multi-pane
          // workspaces are — a floating rounded card would read as page
          // content sitting *inside* a scrolling document, which is
          // exactly the impression this layout must not give.
          overflow: 'hidden',
          // The divider between columns is declared once, here, rather
          // than each column separately deciding its own border and
          // leaving the details panel looking bolted on.
          '& > *:not(:first-of-type)': {
            borderTop: { xs: 1, md: 0 },
            borderLeft: { xs: 0, md: 1 },
            borderColor: 'divider',
          },
        }}
      >
        {/* minHeight: 0 — same flexbox "automatic minimum size" fix as
            AppLayout.tsx's main region. On xs this Box is a column-flex
            sibling of the sidebar below it (the outer Stack switches to
            flexDirection: 'column'); without this it refuses to shrink
            below its content's natural height (Tabs + MessageThread's own
            minimum + ReplyBox), leaving the sidebar's fixed maxHeight:320
            with no actual room inside the workspace's hard height cap. */}
        <Box
          sx={{ display: 'flex', flexDirection: 'column', flexGrow: 1, minWidth: 0, minHeight: 0 }}
        >
          <Tabs
            value={tab}
            onChange={(_event, value) => setTab(value)}
            variant="scrollable"
            scrollButtons="auto"
            sx={{ borderBottom: 1, borderColor: 'divider' }}
          >
            <Tab label={t('ConversationViewPage.messagesTab')} value="messages" />
            <Tab label={t('ConversationViewPage.internalNotesTab')} value="notes" />
            <Tab label={t('ConversationViewPage.transferHistoryTab')} value="transfers" />
          </Tabs>

          {tab === 'messages' && (
            <>
              <MessageThread conversationId={conversation.id} />
              <ReplyBox
                conversationId={conversation.id}
                onTyping={(isTyping) => sendTyping(conversation.id, isTyping)}
              />
            </>
          )}
          {tab === 'notes' && <NotesPanel conversationId={conversation.id} />}
          {tab === 'transfers' && <TransferHistoryPanel conversationId={conversation.id} />}
        </Box>

      </Stack>

      {/* On demand, never permanent. The details panel used to be a
          fifth always-visible column, which cost the chat 280px at all
          times for information an agent needs occasionally. As a
          temporary right-anchored Drawer it overlays instead of
          reflowing, so opening and closing it never resizes the message
          thread — the chat keeps the full width the moment it closes.
          `keepMounted` so its data isn't refetched on every open. */}
      <Drawer
        anchor="right"
        open={detailsOpen}
        onClose={() => setDetailsOpen(false)}
        ModalProps={{ keepMounted: true }}
        slotProps={{
          paper: {
            sx: {
              width: { xs: '100%', sm: DETAILS_PANEL_WIDTH },
              display: 'flex',
              flexDirection: 'column',
            },
          },
        }}
      >
        <Stack
          direction="row"
          sx={{
            alignItems: 'center',
            justifyContent: 'space-between',
            px: 2,
            py: 1.5,
            borderBottom: 1,
            borderColor: 'divider',
            flexShrink: 0,
          }}
        >
          <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
            {t('ConversationViewPage.conversationDetails')}
          </Typography>
          <IconButton
            onClick={() => setDetailsOpen(false)}
            aria-label={t('ConversationViewPage.closeDetailsAriaLabel')}
          >
            <CloseIcon />
          </IconButton>
        </Stack>
        {/* The panel scrolls on its own, like every other column in this
            workspace — a long details panel must never scroll the page. */}
        <Box sx={{ overflowY: 'auto', minHeight: 0, flexGrow: 1 }}>
          <ConversationSidebar
            conversation={conversation}
            customerName={customerQuery.data?.full_name ?? t('ConversationViewPage.emptyValue')}
            customerRatingAverage={customerQuery.data?.rating_average ?? null}
            customerRatingCount={customerQuery.data?.rating_count ?? 0}
          />
        </Box>
      </Drawer>
    </Box>
  )
}

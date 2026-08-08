import { useEffect, useMemo, useRef, useState } from 'react'
import {
  Box,
  CircularProgress,
  InputAdornment,
  List,
  ListItem,
  ListItemButton,
  ListItemText,
  Popover,
  TextField,
  Typography,
} from '@mui/material'
import SearchIcon from '@mui/icons-material/Search'
import { useTranslation } from 'react-i18next'
import { useQuickRepliesQuery } from '../quickReplies/api'
import type { QuickReply } from '../quickReplies/types'

/** How much of a saved reply to preview in the list.
 *
 * Long enough to tell two refund policies apart, short enough that ten
 * of them still fit on screen — the picker is for recognising the one
 * you already know, not for reading. */
const PREVIEW_LENGTH = 90

/** Ranks matches so the shortcut somebody typed comes first.
 *
 * An agent typing `ref` means the `/refund` shortcut, not the reply
 * whose body happens to contain "preferred". Shortcut prefix beats
 * shortcut substring beats title beats body, and the body is searched at
 * all only because the wording is sometimes the only thing anybody
 * remembers.
 */
function rank(reply: QuickReply, needle: string): number {
  const shortcut = reply.shortcut.toLowerCase().replace(/^\//, '')
  if (shortcut.startsWith(needle)) return 0
  if (shortcut.includes(needle)) return 1
  if (reply.title.toLowerCase().includes(needle)) return 2
  if (reply.body.toLowerCase().includes(needle)) return 3
  return -1
}

function filterReplies(replies: QuickReply[], filter: string): QuickReply[] {
  const needle = filter.trim().toLowerCase().replace(/^\//, '')
  if (!needle) return replies
  return replies
    .map((reply) => ({ reply, score: rank(reply, needle) }))
    .filter((entry) => entry.score >= 0)
    .sort((a, b) => a.score - b.score)
    .map((entry) => entry.reply)
}

/**
 * Saved replies, one keystroke from the composer.
 *
 * The phrases a team agrees on — refund policy, opening hours, the
 * apology that legal signed off — have lived in the database since the
 * beginning with no way to reach them from the one screen where they are
 * used. Agents retyped them, which is slower and, worse, means the
 * wording drifts a little every time.
 *
 * Focus moves into the search box rather than staying in the composer.
 * That is a deliberate departure from the inline-autocomplete pattern:
 * the field is visible, so there is never a question of where typing is
 * going, and it works identically whether the picker was opened by the
 * button or by typing a slash.
 */
export function QuickReplyPicker({
  open,
  anchorEl,
  initialFilter = '',
  onSelect,
  onClose,
}: {
  open: boolean
  anchorEl: HTMLElement | null
  /** Pre-seeded when opened by typing `/` followed by some of a shortcut. */
  initialFilter?: string
  onSelect: (reply: QuickReply) => void
  onClose: () => void
}) {
  const { t } = useTranslation('conversationsCore')
  // Seeded once, because the caller mounts this only while it is open —
  // so every open is a fresh component and starts on the first match
  // rather than inheriting where the last one was left.
  const [filter, setFilter] = useState(initialFilter)
  const [highlighted, setHighlighted] = useState(0)
  const listRef = useRef<HTMLUListElement>(null)

  const query = useQuickRepliesQuery(open)
  const replies = useMemo(() => filterReplies(query.data ?? [], filter), [query.data, filter])

  // Clamped at render rather than corrected in an effect: typing one more
  // character can cut the list shorter than the current position, and a
  // highlight past the end would leave Enter doing nothing.
  const activeIndex = highlighted >= replies.length ? 0 : highlighted

  function handleKeyDown(event: React.KeyboardEvent) {
    if (replies.length === 0) return
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      setHighlighted((activeIndex + 1) % replies.length)
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      setHighlighted((activeIndex - 1 + replies.length) % replies.length)
    } else if (event.key === 'Enter') {
      event.preventDefault()
      onSelect(replies[activeIndex])
    }
  }

  useEffect(() => {
    // Keeps the keyboard selection on screen when arrowing past the fold.
    // `scrollIntoView` is absent in jsdom, hence the optional call.
    const node = listRef.current?.children[activeIndex] as HTMLElement | undefined
    node?.scrollIntoView?.({ block: 'nearest' })
  }, [activeIndex])

  return (
    <Popover
      open={open}
      anchorEl={anchorEl}
      onClose={onClose}
      anchorOrigin={{ vertical: 'top', horizontal: 'left' }}
      transformOrigin={{ vertical: 'bottom', horizontal: 'left' }}
      slotProps={{ paper: { sx: { width: 420, maxWidth: '100%' } } }}
    >
      <Box sx={{ p: 1.5, pb: 1 }} onKeyDown={handleKeyDown}>
        <TextField
          autoFocus
          fullWidth
          size="small"
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
          placeholder={t('QuickReplyPicker.searchPlaceholder')}
          slotProps={{
            htmlInput: { 'aria-label': t('QuickReplyPicker.searchAriaLabel') },
            input: {
              startAdornment: (
                <InputAdornment position="start">
                  <SearchIcon fontSize="small" />
                </InputAdornment>
              ),
            },
          }}
        />
      </Box>

      {query.isPending ? (
        <Box sx={{ display: 'flex', justifyContent: 'center', p: 3 }}>
          <CircularProgress size={22} />
        </Box>
      ) : query.isError ? (
        <Box sx={{ px: 2, pb: 2 }}>
          <Typography variant="body2" color="error">
            {t('QuickReplyPicker.loadFailed')}
          </Typography>
        </Box>
      ) : replies.length === 0 ? (
        <Box sx={{ px: 2, pb: 2 }}>
          <Typography variant="body2" color="text.secondary">
            {/* Two different pieces of news: nothing matches what you
                typed, versus nobody has written any saved replies yet.
                The second one is a job for an administrator, so it says
                so rather than looking like a failed search. */}
            {(query.data ?? []).length === 0
              ? t('QuickReplyPicker.noneConfigured')
              : t('QuickReplyPicker.noMatches', { query: filter.trim() })}
          </Typography>
        </Box>
      ) : (
        <List
          ref={listRef}
          dense
          disablePadding
          sx={{ maxHeight: 300, overflowY: 'auto', pb: 1 }}
          aria-label={t('QuickReplyPicker.listAriaLabel')}
          onKeyDown={handleKeyDown}
        >
          {replies.map((reply, index) => (
            <ListItem key={reply.id} disablePadding>
              <ListItemButton
                selected={index === activeIndex}
                onClick={() => onSelect(reply)}
                onMouseEnter={() => setHighlighted(index)}
              >
                <ListItemText
                  primary={
                    <Box component="span" sx={{ display: 'flex', gap: 1, alignItems: 'baseline' }}>
                      <Box
                        component="code"
                        sx={{
                          bgcolor: 'action.hover',
                          px: 0.5,
                          borderRadius: 0.5,
                          fontSize: '.8em',
                          flexShrink: 0,
                        }}
                      >
                        {reply.shortcut}
                      </Box>
                      <Box component="span" sx={{ fontWeight: 600, minWidth: 0 }}>
                        {reply.title}
                      </Box>
                    </Box>
                  }
                  secondary={
                    reply.body.length > PREVIEW_LENGTH
                      ? `${reply.body.slice(0, PREVIEW_LENGTH).trimEnd()}…`
                      : reply.body
                  }
                  slotProps={{
                    primary: { variant: 'body2' },
                    secondary: { variant: 'caption', noWrap: true },
                  }}
                />
              </ListItemButton>
            </ListItem>
          ))}
        </List>
      )}
    </Popover>
  )
}

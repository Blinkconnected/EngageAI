import { useId, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
  Box,
  Dialog,
  DialogContent,
  InputAdornment,
  List,
  ListItem,
  ListItemButton,
  ListItemText,
  TextField,
  Typography,
} from '@mui/material'
import SearchIcon from '@mui/icons-material/Search'
import { LoadingState } from '../../shared/components/LoadingState'
import { ErrorState } from '../../shared/components/ErrorState'
import { EmptyState } from '../../shared/components/EmptyState'
import { useDebouncedValue } from '../../shared/hooks/useDebouncedValue'
import { useSearchQuery } from './api'
import {
  MIN_SEARCH_QUERY_LENGTH,
  SEARCH_ENTITY_TYPE_ORDER,
  SEARCH_RESULT_PATHS,
  type SearchEntityType,
  type SearchHit,
} from './types'

const DEBOUNCE_MS = 250

export function GlobalSearchDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useTranslation('search')
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  const debouncedQuery = useDebouncedValue(query, DEBOUNCE_MS)
  const titleId = useId()

  const searchQuery = useSearchQuery(debouncedQuery)

  const grouped = useMemo(() => {
    const byType = new Map<SearchEntityType, SearchHit[]>()
    for (const hit of searchQuery.data?.results ?? []) {
      const existing = byType.get(hit.entity_type)
      if (existing) existing.push(hit)
      else byType.set(hit.entity_type, [hit])
    }
    return SEARCH_ENTITY_TYPE_ORDER.filter((type) => byType.has(type)).map((type) => ({
      type,
      hits: byType.get(type) as SearchHit[],
    }))
  }, [searchQuery.data])

  function handleClose() {
    setQuery('')
    onClose()
  }

  function handleSelect(hit: SearchHit) {
    const toPath = SEARCH_RESULT_PATHS[hit.entity_type]
    if (!toPath) return
    handleClose()
    navigate(toPath(hit.id))
  }

  const isTooShort = debouncedQuery.trim().length < MIN_SEARCH_QUERY_LENGTH
  const hasResults = grouped.length > 0

  return (
    <Dialog
      open={open}
      onClose={handleClose}
      fullWidth
      maxWidth="sm"
      aria-labelledby={titleId}
      // Anchored near the top rather than vertically centered — the
      // result list grows downward as you type, and a centered dialog
      // would jump around on every keystroke.
      slotProps={{ paper: { sx: { position: 'absolute', top: 64, m: 0 } } }}
    >
      <Box sx={{ p: 2, pb: 1 }}>
        <Typography id={titleId} variant="subtitle2" sx={{ mb: 1 }}>
          {t('GlobalSearchDialog.title')}
        </Typography>
        <TextField
          autoFocus
          fullWidth
          size="small"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={t('GlobalSearchDialog.placeholder')}
          slotProps={{
            // `aria-label` must go on the `<input>` itself (htmlInput),
            // not the TextField root — MUI forwards a root-level
            // aria-label to the wrapper div, which would leave the real
            // input unlabelled for screen readers (and for any
            // getByLabelText query).
            htmlInput: { 'aria-label': t('GlobalSearchDialog.inputAriaLabel') },
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

      <DialogContent dividers sx={{ p: 0, maxHeight: 420 }}>
        {isTooShort && (
          <Box sx={{ p: 3 }}>
            <Typography variant="body2" color="text.secondary" align="center">
              {t('GlobalSearchDialog.minLengthHint', { count: MIN_SEARCH_QUERY_LENGTH })}
            </Typography>
          </Box>
        )}

        {!isTooShort && searchQuery.isPending && (
          <LoadingState label={t('GlobalSearchDialog.loadingLabel')} />
        )}

        {!isTooShort && searchQuery.isError && (
          <ErrorState error={searchQuery.error} onRetry={() => searchQuery.refetch()} />
        )}

        {!isTooShort && searchQuery.data && !hasResults && (
          <Box sx={{ p: 2 }}>
            <EmptyState
              title={t('GlobalSearchDialog.noResultsTitle')}
              description={t('GlobalSearchDialog.noResultsDescription', {
                query: debouncedQuery.trim(),
              })}
            />
          </Box>
        )}

        {/* One <List> per group, each labelled by its own heading, rather
            than a single List with ListSubheaders — nesting a <ul> inside
            an <li> to scope subheaders is what axe flags, and separate
            labelled lists are the clearer structure for a screen reader
            anyway ("Customers, list, 3 items"). */}
        {hasResults &&
          grouped.map((group) => {
            const label = t(`GlobalSearchDialog.groupLabels.${group.type}`)
            return (
              <Box key={group.type}>
                <Typography
                  variant="overline"
                  color="text.secondary"
                  component="h3"
                  sx={{ px: 2, pt: 1.5, display: 'block' }}
                >
                  {label}
                </Typography>
                <List dense disablePadding aria-label={label}>
                  {group.hits.map((hit) => {
                    const navigable = SEARCH_RESULT_PATHS[hit.entity_type] !== null
                    return (
                      // ListItem (an <li>) wraps the button so the <ul>
                      // only ever contains <li> children — a bare
                      // ListItemButton renders a <div>, which axe
                      // correctly flags as invalid list markup.
                      <ListItem key={`${hit.entity_type}:${hit.id}`} disablePadding>
                        <ListItemButton onClick={() => handleSelect(hit)} disabled={!navigable}>
                          <ListItemText
                            primary={hit.title}
                            secondary={
                              navigable
                                ? hit.subtitle
                                : // Explains the disabled row rather
                                  // than leaving it looking broken.
                                  t('GlobalSearchDialog.noPageYet')
                            }
                          />
                        </ListItemButton>
                      </ListItem>
                    )
                  })}
                </List>
              </Box>
            )
          })}
      </DialogContent>
    </Dialog>
  )
}

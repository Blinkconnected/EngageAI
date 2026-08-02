import { InputAdornment, TextField } from '@mui/material'
import SearchIcon from '@mui/icons-material/Search'
import { useTranslation } from 'react-i18next'

/** Searches the whole story, not just the titles.
 *
 * Matching runs over the title, the explanation, every "why" and "impact"
 * line and the supporting values — because the thing somebody remembers is
 * rarely the event's name. "waiting for the customer" is a pause reason,
 * "0.6" is a threshold, and both should find their event.
 */
export function TimelineSearch({
  value,
  onChange,
}: {
  value: string
  onChange: (next: string) => void
}) {
  const { t } = useTranslation('inspector')
  return (
    <TextField
      size="small"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={t('search.placeholder')}
      slotProps={{
        htmlInput: { 'aria-label': t('search.label') },
        input: {
          startAdornment: (
            <InputAdornment position="start">
              <SearchIcon fontSize="small" />
            </InputAdornment>
          ),
        },
      }}
      sx={{ minWidth: { xs: '100%', sm: 260 } }}
    />
  )
}

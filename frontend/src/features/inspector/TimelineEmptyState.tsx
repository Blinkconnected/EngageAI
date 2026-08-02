import { Box, Typography } from '@mui/material'
import { useTranslation } from 'react-i18next'

/** Two different nothings, told apart.
 *
 * A conversation with no recorded events and a filter that matched none of
 * them look identical if both render a blank panel — and they send a reader
 * to very different places. The second is a control the reader can undo;
 * the first is a fact about the conversation.
 */
export function TimelineEmptyState({ filtered, gaps }: { filtered: boolean; gaps: string[] }) {
  const { t } = useTranslation('inspector')

  return (
    <Box sx={{ py: 6, px: 3, textAlign: 'center' }}>
      <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
        {filtered ? t('empty.filteredTitle') : t('empty.title')}
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
        {filtered ? t('empty.filteredBody') : t('empty.body')}
      </Typography>
      {!filtered && gaps.length > 0 ? (
        <Box sx={{ mt: 2, mx: 'auto', maxWidth: 520, textAlign: 'start' }}>
          {gaps.map((gap) => (
            <Typography key={gap} variant="body2" color="text.secondary" sx={{ mb: 0.5 }}>
              {gap}
            </Typography>
          ))}
        </Box>
      ) : null}
    </Box>
  )
}

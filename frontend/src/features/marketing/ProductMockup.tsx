import { Box, Chip, Paper, Stack, Typography } from '@mui/material'
import { useTranslation } from 'react-i18next'

/**
 * A depiction of the Inbox, drawn with the same components the real one
 * uses.
 *
 * Deliberately not a screenshot. A screenshot of a real workspace would
 * contain a real customer's name and message, which must never appear in
 * marketing material; a screenshot of a seeded demo workspace goes stale
 * the moment the interface changes and nobody notices for a year. Drawing
 * it from the live theme means it follows light/dark and RTL for free and
 * cannot show a layout the product no longer has.
 *
 * The content is illustrative and labelled as such to assistive
 * technology — it is a picture of the product, not live data.
 */
export function ProductMockup() {
  const { t } = useTranslation('marketing')

  const rows = ['first', 'second', 'third'] as const

  return (
    <Paper
      elevation={0}
      role="img"
      aria-label={t('ProductMockup.ariaLabel')}
      sx={{
        border: 1,
        borderColor: 'divider',
        borderRadius: 3,
        overflow: 'hidden',
        bgcolor: 'background.paper',
        boxShadow: (theme) =>
          theme.palette.mode === 'dark'
            ? '0 24px 60px rgba(0,0,0,.55)'
            : '0 24px 60px rgba(16,24,40,.14)',
      }}
    >
      {/* Window chrome — three dots read as "this is an application". */}
      <Stack
        direction="row"
        spacing={1}
        sx={{
          px: 2,
          py: 1.25,
          borderBottom: 1,
          borderColor: 'divider',
          bgcolor: 'action.hover',
          alignItems: 'center',
        }}
      >
        {['#ff5f57', '#febc2e', '#28c840'].map((colour) => (
          <Box key={colour} sx={{ width: 10, height: 10, borderRadius: '50%', bgcolor: colour }} />
        ))}
        <Typography variant="caption" color="text.secondary" sx={{ ml: 1 }}>
          {t('ProductMockup.title')}
        </Typography>
      </Stack>

      <Stack direction="row" sx={{ minHeight: 320 }}>
        {/* Conversation list */}
        <Box
          sx={{
            width: { xs: '100%', sm: 260 },
            borderInlineEnd: 1,
            borderColor: 'divider',
            display: { xs: 'none', sm: 'block' },
          }}
        >
          {rows.map((row, index) => (
            <Stack
              key={row}
              spacing={0.75}
              sx={{
                p: 1.75,
                borderBottom: 1,
                borderColor: 'divider',
                bgcolor: index === 0 ? 'action.selected' : 'transparent',
              }}
            >
              <Stack direction="row" sx={{ justifyContent: 'space-between', alignItems: 'center' }}>
                <Typography variant="body2" sx={{ fontWeight: 600 }}>
                  {t(`ProductMockup.rows.${row}.name`)}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  {t(`ProductMockup.rows.${row}.time`)}
                </Typography>
              </Stack>
              <Typography variant="caption" color="text.secondary" noWrap>
                {t(`ProductMockup.rows.${row}.preview`)}
              </Typography>
              <Stack direction="row" spacing={0.5}>
                <Chip
                  size="small"
                  label={t(`ProductMockup.rows.${row}.channel`)}
                  sx={{ height: 20, fontSize: 11 }}
                />
                <Chip
                  size="small"
                  color={index === 1 ? 'warning' : 'default'}
                  variant={index === 1 ? 'filled' : 'outlined'}
                  label={t(`ProductMockup.rows.${row}.badge`)}
                  sx={{ height: 20, fontSize: 11 }}
                />
              </Stack>
            </Stack>
          ))}
        </Box>

        {/* Conversation */}
        <Stack sx={{ flex: 1, p: 2.5 }} spacing={2}>
          <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
            {/* component="p" because MUI renders subtitle2 as an <h6>,
                and this illustration sits inside the hero where the only
                real heading is the page h1. */}
            <Typography variant="subtitle2" component="p" sx={{ fontWeight: 700 }}>
              {t('ProductMockup.rows.first.name')}
            </Typography>
            <Chip
              size="small"
              label={t('ProductMockup.conversation.status')}
              sx={{ height: 20, fontSize: 11 }}
            />
          </Stack>

          <Stack spacing={1.5}>
            <Bubble side="start" text={t('ProductMockup.conversation.inbound')} />
            <Bubble side="end" text={t('ProductMockup.conversation.outbound')} />
          </Stack>

          <Box sx={{ flexGrow: 1 }} />

          <Paper variant="outlined" sx={{ p: 1.5, borderRadius: 2, bgcolor: 'action.hover' }}>
            <Typography variant="caption" color="text.secondary">
              {t('ProductMockup.conversation.aiHint')}
            </Typography>
          </Paper>
        </Stack>
      </Stack>
    </Paper>
  )
}

function Bubble({ side, text }: { side: 'start' | 'end'; text: string }) {
  const isOutbound = side === 'end'
  return (
    <Box sx={{ display: 'flex', justifyContent: isOutbound ? 'flex-end' : 'flex-start' }}>
      <Paper
        elevation={0}
        sx={{
          px: 1.75,
          py: 1.25,
          maxWidth: '80%',
          borderRadius: 2,
          bgcolor: isOutbound ? 'primary.main' : 'action.hover',
          color: isOutbound ? 'primary.contrastText' : 'text.primary',
        }}
      >
        <Typography variant="body2">{text}</Typography>
      </Paper>
    </Box>
  )
}

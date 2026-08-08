import { useMemo, useState } from 'react'
import {
  Alert,
  Box,
  InputAdornment,
  Link,
  List,
  ListItemButton,
  ListItemText,
  Paper,
  Stack,
  TextField,
  Typography,
} from '@mui/material'
import SearchIcon from '@mui/icons-material/Search'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { useTranslation } from 'react-i18next'
import { PageHeader } from '../../shared/components/PageHeader'
import { LoadingState } from '../../shared/components/LoadingState'
import { ErrorState } from '../../shared/components/ErrorState'
import { useGuideQuery } from './api'
import { splitIntoSections, type GuideSection } from './sections'

/**
 * The product guide, inside the product.
 *
 * The guide already existed as a Markdown file that everybody except the
 * customer could read. Fetching that same file rather than re-typing it
 * into the translation catalogue is deliberate: a second copy drifts, and
 * the copy that drifts is always the one the customer is reading.
 *
 * Split into sections client-side rather than served pre-chunked. The
 * guide's headings are its structure; parsing them here means adding a
 * section to the document is all it takes to add one here, with no
 * endpoint change and nothing to keep in step.
 */
export function HelpPage() {
  const { t } = useTranslation('help')
  const guideQuery = useGuideQuery()
  const [selected, setSelected] = useState<string | null>(null)
  const [search, setSearch] = useState('')

  const sections = useMemo<GuideSection[]>(
    () => (guideQuery.data ? splitIntoSections(guideQuery.data.content) : []),
    [guideQuery.data],
  )

  const matches = useMemo(() => {
    const query = search.trim().toLowerCase()
    if (!query) return sections
    // Body as well as title: somebody searching "business hours" should
    // reach the SLA section, whose heading does not contain those words.
    return sections.filter(
      (section) =>
        section.title.toLowerCase().includes(query) || section.body.toLowerCase().includes(query),
    )
  }, [sections, search])

  const active = matches.find((section) => section.id === selected) ?? matches[0] ?? null

  if (guideQuery.isPending) return <LoadingState label={t('HelpPage.loading')} />
  if (guideQuery.isError) {
    return <ErrorState error={guideQuery.error} onRetry={() => guideQuery.refetch()} />
  }

  return (
    <Stack spacing={3}>
      <PageHeader title={t('HelpPage.title')} description={t('HelpPage.description')} />

      {guideQuery.data?.fell_back && (
        // Said out loud rather than silently serving English: an Arabic
        // reader seeing English text otherwise has no way to tell whether
        // the translation is missing or the page is broken.
        <Alert severity="info">{t('HelpPage.englishFallback')}</Alert>
      )}

      <Stack direction={{ xs: 'column', md: 'row' }} spacing={3} sx={{ alignItems: 'flex-start' }}>
        <Paper
          variant="outlined"
          sx={{
            width: { xs: '100%', md: 300 },
            flexShrink: 0,
            position: { md: 'sticky' },
            top: 16,
          }}
        >
          <Box sx={{ p: 1.5 }}>
            <TextField
              fullWidth
              size="small"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder={t('HelpPage.searchPlaceholder')}
              slotProps={{
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
          <List dense sx={{ maxHeight: { md: '70vh' }, overflowY: 'auto', pt: 0 }}>
            {matches.map((section) => (
              <ListItemButton
                key={section.id}
                selected={section.id === active?.id}
                onClick={() => setSelected(section.id)}
              >
                <ListItemText
                  primary={section.title}
                  slotProps={{ primary: { variant: 'body2' } }}
                />
              </ListItemButton>
            ))}
            {matches.length === 0 && (
              <Box sx={{ px: 2, py: 3 }}>
                <Typography variant="body2" color="text.secondary">
                  {t('HelpPage.noResults', { query: search })}
                </Typography>
              </Box>
            )}
          </List>
        </Paper>

        <Paper variant="outlined" sx={{ flex: 1, p: { xs: 2, md: 4 }, minWidth: 0 }}>
          {active ? (
            <Box
              sx={{
                // The guide is long-form prose. These bring Markdown
                // output in line with the rest of the product rather than
                // leaving it looking like a raw document.
                '& h1': { typography: 'h4', fontWeight: 700, mt: 0, mb: 2 },
                '& h2': { typography: 'h5', fontWeight: 600, mt: 4, mb: 1.5 },
                '& h3': { typography: 'h6', fontWeight: 600, mt: 3, mb: 1 },
                '& p': { typography: 'body2', lineHeight: 1.8, mb: 2 },
                '& li': { typography: 'body2', lineHeight: 1.8 },
                '& table': {
                  width: '100%',
                  borderCollapse: 'collapse',
                  mb: 3,
                  display: 'block',
                  // Wide tables scroll inside themselves rather than
                  // pushing the whole page sideways.
                  overflowX: 'auto',
                },
                '& th, & td': {
                  border: 1,
                  borderColor: 'divider',
                  p: 1,
                  typography: 'body2',
                  textAlign: 'start',
                },
                '& th': { bgcolor: 'action.hover', fontWeight: 600 },
                '& blockquote': {
                  m: 0,
                  mb: 2,
                  px: 2,
                  py: 1,
                  borderInlineStart: 4,
                  borderColor: 'primary.main',
                  bgcolor: 'action.hover',
                  '& p': { mb: 0 },
                },
                '& code': {
                  bgcolor: 'action.hover',
                  px: 0.5,
                  borderRadius: 0.5,
                  fontSize: '.85em',
                },
                '& pre': { bgcolor: 'action.hover', p: 2, borderRadius: 1, overflowX: 'auto' },
                '& img': { maxWidth: '100%' },
              }}
            >
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  // Internal document links point at anchors in a file
                  // nobody outside the repository can open, so they are
                  // rendered as plain text rather than dead links.
                  a: ({ href, children }) =>
                    href?.startsWith('http') ? (
                      <Link href={href} target="_blank" rel="noopener noreferrer">
                        {children}
                      </Link>
                    ) : (
                      <span>{children}</span>
                    ),
                }}
              >
                {active.body}
              </ReactMarkdown>
            </Box>
          ) : (
            <Typography variant="body2" color="text.secondary">
              {t('HelpPage.noResults', { query: search })}
            </Typography>
          )}
        </Paper>
      </Stack>
    </Stack>
  )
}

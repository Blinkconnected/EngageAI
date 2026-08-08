import { Link as RouterLink } from 'react-router-dom'
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  AppBar,
  Box,
  Button,
  Chip,
  Container,
  Divider,
  Grid,
  Link,
  Paper,
  Stack,
  Toolbar,
  Typography,
} from '@mui/material'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutlineOutlined'
import LockOutlinedIcon from '@mui/icons-material/LockOutlined'
import VerifiedUserOutlinedIcon from '@mui/icons-material/VerifiedUserOutlined'
import HistoryEduOutlinedIcon from '@mui/icons-material/HistoryEduOutlined'
import PublicOutlinedIcon from '@mui/icons-material/PublicOutlined'
import ForumOutlinedIcon from '@mui/icons-material/ForumOutlined'
import SmartToyOutlinedIcon from '@mui/icons-material/SmartToyOutlined'
import AltRouteOutlinedIcon from '@mui/icons-material/AltRouteOutlined'
import TimerOutlinedIcon from '@mui/icons-material/TimerOutlined'
import MenuBookOutlinedIcon from '@mui/icons-material/MenuBookOutlined'
import AssessmentOutlinedIcon from '@mui/icons-material/AssessmentOutlined'
import HubOutlinedIcon from '@mui/icons-material/HubOutlined'
import ShieldOutlinedIcon from '@mui/icons-material/ShieldOutlined'
import ContactsOutlinedIcon from '@mui/icons-material/ContactsOutlined'
import { useTranslation } from 'react-i18next'
import type { ComponentType } from 'react'
import { LanguageThemeControls } from '../../shared/components/LanguageThemeControls'
import { ProductMockup } from './ProductMockup'
import logoLight from '../../assets/logo-light.png'

/**
 * The public face of the platform, at `/`.
 *
 * Until now an anonymous visitor to the root was redirected straight to a
 * sign-in form, which told somebody evaluating the product nothing at
 * all. This page answers "what is this?" before asking anybody to
 * authenticate, and keeps sign-in one click away for the people who use
 * it daily.
 *
 * **Every claim here is checked against what the product actually does.**
 * That constraint is the reason this file is written by hand rather than
 * generated from a marketing brief: a landing page promising a feature
 * that does not exist is a refund and a bad reference, and this codebase
 * has already had to correct a user guide that described two screens
 * nobody built.
 */

interface FeatureCard {
  icon: ComponentType<{ fontSize?: 'small' | 'medium' | 'large' | 'inherit' }>
  key: string
}

const FEATURES: FeatureCard[] = [
  { icon: ForumOutlinedIcon, key: 'inbox' },
  { icon: SmartToyOutlinedIcon, key: 'ai' },
  { icon: AltRouteOutlinedIcon, key: 'routing' },
  { icon: TimerOutlinedIcon, key: 'sla' },
  { icon: ContactsOutlinedIcon, key: 'customers' },
  { icon: MenuBookOutlinedIcon, key: 'knowledge' },
  { icon: AssessmentOutlinedIcon, key: 'reports' },
  { icon: HubOutlinedIcon, key: 'intelligence' },
  { icon: ShieldOutlinedIcon, key: 'security' },
]

/** Channel names are product nouns, not translated strings. */
const CHANNELS = [
  'WhatsApp',
  'Facebook Messenger',
  'Instagram',
  'Telegram',
  'Email',
  'SMS',
  'Web Chat',
] as const

const STEPS = ['arrives', 'routed', 'answered', 'measured'] as const

/** Counts a reader can check against the product, not invented figures. */
const STATS = ['channels', 'clocks', 'reports', 'languages'] as const

/** Longer sections for the three things people ask most about. */
const DEEP_DIVES = ['ai', 'sla', 'intelligence'] as const

const SECURITY = [
  { icon: LockOutlinedIcon, key: 'isolation' },
  { icon: VerifiedUserOutlinedIcon, key: 'permissions' },
  { icon: HistoryEduOutlinedIcon, key: 'audit' },
  { icon: PublicOutlinedIcon, key: 'local' },
] as const

const FAQS = ['setup', 'channels', 'ai', 'data', 'languages', 'migrate', 'size', 'support'] as const

const AUDIENCES = ['smb', 'enterprise', 'government', 'healthcare', 'financial'] as const

export function LandingPage() {
  const { t } = useTranslation('marketing')

  return (
    <Box sx={{ bgcolor: 'background.default', minHeight: '100%' }}>
      <AppBar
        position="sticky"
        color="inherit"
        elevation={0}
        sx={{ borderBottom: 1, borderColor: 'divider' }}
      >
        <Container maxWidth="lg">
          <Toolbar disableGutters sx={{ gap: 2 }}>
            <Box
              component="img"
              src={logoLight}
              alt={t('LandingPage.logoAlt')}
              sx={{ height: 32 }}
            />
            <Box sx={{ flexGrow: 1 }} />
            <LanguageThemeControls />
            <Button component={RouterLink} to="/login" variant="text">
              {t('LandingPage.signIn')}
            </Button>
            <Button component={RouterLink} to="/register" variant="contained">
              {t('LandingPage.getStarted')}
            </Button>
          </Toolbar>
        </Container>
      </AppBar>

      {/* Hero */}
      <Box
        component="section"
        sx={{
          py: { xs: 7, md: 12 },
          position: 'relative',
          overflow: 'hidden',
          // A tint rather than a photograph: it follows the theme, costs
          // nothing to load, and cannot look dated the way stock imagery
          // does within a year.
          background: (theme) =>
            theme.palette.mode === 'dark'
              ? `radial-gradient(1200px 500px at 15% -10%, ${theme.palette.primary.dark}33, transparent 60%)`
              : `radial-gradient(1200px 500px at 15% -10%, ${theme.palette.primary.light}44, transparent 60%)`,
        }}
      >
        <Container maxWidth="lg">
          <Grid container spacing={{ xs: 5, md: 6 }} sx={{ alignItems: 'center' }}>
            <Grid size={{ xs: 12, md: 6 }}>
              <Stack spacing={3}>
                <Chip
                  label={t('LandingPage.hero.badge')}
                  color="primary"
                  variant="outlined"
                  sx={{ alignSelf: 'flex-start', fontWeight: 600 }}
                />
                <Typography variant="h2" component="h1" sx={{ fontWeight: 700, lineHeight: 1.12 }}>
                  {t('LandingPage.hero.title')}
                </Typography>
                <Typography
                  variant="h6"
                  component="p"
                  color="text.secondary"
                  sx={{ fontWeight: 400 }}
                >
                  {t('LandingPage.hero.subtitle')}
                </Typography>
                <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} sx={{ pt: 1 }}>
                  <Button component={RouterLink} to="/register" size="large" variant="contained">
                    {t('LandingPage.hero.primaryCta')}
                  </Button>
                  <Button component={RouterLink} to="/login" size="large" variant="outlined">
                    {t('LandingPage.hero.secondaryCta')}
                  </Button>
                </Stack>
                <Typography variant="body2" color="text.secondary">
                  {t('LandingPage.hero.reassurance')}
                </Typography>
              </Stack>
            </Grid>
            <Grid size={{ xs: 12, md: 6 }}>
              <ProductMockup />
            </Grid>
          </Grid>
        </Container>
      </Box>

      {/* Numbers a reader can verify in the product itself. */}
      <Box component="section" sx={{ py: { xs: 4, md: 5 }, borderY: 1, borderColor: 'divider' }}>
        <Container maxWidth="lg">
          <Grid container spacing={3}>
            {STATS.map((stat) => (
              <Grid key={stat} size={{ xs: 6, md: 3 }}>
                <Stack spacing={0.5}>
                  {/* component="p": these are display figures, not
                      headings. MUI maps variant="h3" to an <h3> element,
                      which put a heading-order jump straight after the
                      page h1 and failed the axe check. */}
                  <Typography
                    variant="h3"
                    component="p"
                    sx={{ fontWeight: 700, color: 'primary.main' }}
                  >
                    {t(`LandingPage.stats.${stat}.value`)}
                  </Typography>
                  <Typography variant="body2" color="text.secondary">
                    {t(`LandingPage.stats.${stat}.label`)}
                  </Typography>
                </Stack>
              </Grid>
            ))}
          </Grid>
        </Container>
      </Box>

      {/* Channels */}
      <Box component="section" sx={{ py: { xs: 4, md: 6 }, bgcolor: 'action.hover' }}>
        <Container maxWidth="lg">
          <Typography variant="overline" color="text.secondary">
            {t('LandingPage.channels.eyebrow')}
          </Typography>
          <Typography variant="h4" component="h2" sx={{ fontWeight: 600, mt: 1, mb: 3 }}>
            {t('LandingPage.channels.title')}
          </Typography>
          <Stack direction="row" spacing={1.5} sx={{ flexWrap: 'wrap' }} useFlexGap>
            {CHANNELS.map((channel) => (
              <Paper
                key={channel}
                variant="outlined"
                sx={{ px: 2, py: 1, borderRadius: 5, bgcolor: 'background.paper' }}
              >
                <Typography variant="body2" sx={{ fontWeight: 500 }}>
                  {channel}
                </Typography>
              </Paper>
            ))}
          </Stack>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 3, maxWidth: 720 }}>
            {t('LandingPage.channels.note')}
          </Typography>
        </Container>
      </Box>

      {/* How it works */}
      <Box component="section" sx={{ py: { xs: 6, md: 8 } }}>
        <Container maxWidth="lg">
          <Typography variant="h4" component="h2" sx={{ fontWeight: 600, mb: 1 }}>
            {t('LandingPage.how.title')}
          </Typography>
          <Typography color="text.secondary" sx={{ mb: 4, maxWidth: 720 }}>
            {t('LandingPage.how.subtitle')}
          </Typography>
          <Grid container spacing={3}>
            {STEPS.map((step, index) => (
              <Grid key={step} size={{ xs: 12, sm: 6, md: 3 }}>
                <Stack spacing={1.5}>
                  <Box
                    aria-hidden
                    sx={{
                      width: 36,
                      height: 36,
                      borderRadius: '50%',
                      display: 'grid',
                      placeItems: 'center',
                      bgcolor: 'primary.main',
                      color: 'primary.contrastText',
                      fontWeight: 700,
                    }}
                  >
                    {index + 1}
                  </Box>
                  <Typography variant="h6" component="h3" sx={{ fontWeight: 600 }}>
                    {t(`LandingPage.how.steps.${step}.title`)}
                  </Typography>
                  <Typography variant="body2" color="text.secondary">
                    {t(`LandingPage.how.steps.${step}.body`)}
                  </Typography>
                </Stack>
              </Grid>
            ))}
          </Grid>
        </Container>
      </Box>

      {/* Features */}
      <Box component="section" sx={{ py: { xs: 6, md: 8 }, bgcolor: 'action.hover' }}>
        <Container maxWidth="lg">
          <Typography variant="h4" component="h2" sx={{ fontWeight: 600, mb: 1 }}>
            {t('LandingPage.features.title')}
          </Typography>
          <Typography color="text.secondary" sx={{ mb: 4, maxWidth: 720 }}>
            {t('LandingPage.features.subtitle')}
          </Typography>
          <Grid container spacing={3}>
            {FEATURES.map(({ icon: Icon, key }) => (
              <Grid key={key} size={{ xs: 12, sm: 6, md: 4 }}>
                <Paper
                  variant="outlined"
                  sx={{ p: 3, height: '100%', bgcolor: 'background.paper' }}
                >
                  <Stack spacing={1.5}>
                    <Box sx={{ color: 'primary.main', display: 'flex' }}>
                      <Icon fontSize="large" />
                    </Box>
                    <Typography variant="h6" component="h3" sx={{ fontWeight: 600 }}>
                      {t(`LandingPage.features.items.${key}.title`)}
                    </Typography>
                    <Typography variant="body2" color="text.secondary">
                      {t(`LandingPage.features.items.${key}.body`)}
                    </Typography>
                  </Stack>
                </Paper>
              </Grid>
            ))}
          </Grid>
        </Container>
      </Box>

      {/* Deep dives — alternating, for the three things people ask about */}
      <Box component="section" sx={{ py: { xs: 6, md: 10 } }}>
        <Container maxWidth="lg">
          <Stack spacing={{ xs: 6, md: 10 }}>
            {DEEP_DIVES.map((topic, index) => (
              <Grid
                key={topic}
                container
                spacing={{ xs: 3, md: 6 }}
                sx={{ alignItems: 'center' }}
                direction={index % 2 === 1 ? 'row-reverse' : 'row'}
              >
                <Grid size={{ xs: 12, md: 6 }}>
                  <Stack spacing={2}>
                    <Typography variant="overline" color="primary.main" sx={{ fontWeight: 700 }}>
                      {t(`LandingPage.deepDives.${topic}.eyebrow`)}
                    </Typography>
                    <Typography variant="h4" component="h2" sx={{ fontWeight: 600 }}>
                      {t(`LandingPage.deepDives.${topic}.title`)}
                    </Typography>
                    <Typography color="text.secondary">
                      {t(`LandingPage.deepDives.${topic}.body`)}
                    </Typography>
                    <Stack component="ul" spacing={1.25} sx={{ listStyle: 'none', p: 0, m: 0 }}>
                      {['one', 'two', 'three'].map((point) => (
                        <Stack
                          key={point}
                          component="li"
                          direction="row"
                          spacing={1.5}
                          sx={{ alignItems: 'flex-start' }}
                        >
                          <CheckCircleOutlineIcon
                            fontSize="small"
                            sx={{ color: 'success.main', mt: 0.25 }}
                          />
                          <Typography variant="body2" color="text.secondary">
                            {t(`LandingPage.deepDives.${topic}.points.${point}`)}
                          </Typography>
                        </Stack>
                      ))}
                    </Stack>
                  </Stack>
                </Grid>
                <Grid size={{ xs: 12, md: 6 }}>
                  <Paper
                    variant="outlined"
                    sx={{
                      p: { xs: 3, md: 4 },
                      borderRadius: 3,
                      bgcolor: 'action.hover',
                      minHeight: 200,
                      display: 'flex',
                      alignItems: 'center',
                    }}
                  >
                    <Typography
                      variant="h6"
                      component="p"
                      sx={{ fontWeight: 400, fontStyle: 'italic', color: 'text.secondary' }}
                    >
                      {t(`LandingPage.deepDives.${topic}.pullQuote`)}
                    </Typography>
                  </Paper>
                </Grid>
              </Grid>
            ))}
          </Stack>
        </Container>
      </Box>

      {/* Security */}
      <Box component="section" sx={{ py: { xs: 6, md: 8 }, bgcolor: 'action.hover' }}>
        <Container maxWidth="lg">
          <Typography variant="h4" component="h2" sx={{ fontWeight: 600, mb: 1 }}>
            {t('LandingPage.security.title')}
          </Typography>
          <Typography color="text.secondary" sx={{ mb: 4, maxWidth: 720 }}>
            {t('LandingPage.security.subtitle')}
          </Typography>
          <Grid container spacing={3}>
            {SECURITY.map(({ icon: Icon, key }) => (
              <Grid key={key} size={{ xs: 12, sm: 6, md: 3 }}>
                <Stack spacing={1.5}>
                  <Box sx={{ color: 'primary.main', display: 'flex' }}>
                    <Icon fontSize="large" />
                  </Box>
                  <Typography variant="subtitle1" component="h3" sx={{ fontWeight: 600 }}>
                    {t(`LandingPage.security.items.${key}.title`)}
                  </Typography>
                  <Typography variant="body2" color="text.secondary">
                    {t(`LandingPage.security.items.${key}.body`)}
                  </Typography>
                </Stack>
              </Grid>
            ))}
          </Grid>
        </Container>
      </Box>

      {/* Who it is for */}
      <Box component="section" sx={{ py: { xs: 6, md: 8 } }}>
        <Container maxWidth="lg">
          <Typography variant="h4" component="h2" sx={{ fontWeight: 600, mb: 1 }}>
            {t('LandingPage.audience.title')}
          </Typography>
          <Typography color="text.secondary" sx={{ mb: 4, maxWidth: 720 }}>
            {t('LandingPage.audience.subtitle')}
          </Typography>
          <Grid container spacing={2}>
            {AUDIENCES.map((audience) => (
              <Grid key={audience} size={{ xs: 12, sm: 6, md: 4 }}>
                <Stack spacing={0.5}>
                  {/* component="h3" because MUI renders subtitle1 as an
                      <h6> by default, which jumps from the section's h2
                      and fails heading-order for screen readers. */}
                  <Typography variant="subtitle1" component="h3" sx={{ fontWeight: 600 }}>
                    {t(`LandingPage.audience.items.${audience}.title`)}
                  </Typography>
                  <Typography variant="body2" color="text.secondary">
                    {t(`LandingPage.audience.items.${audience}.body`)}
                  </Typography>
                </Stack>
              </Grid>
            ))}
          </Grid>
        </Container>
      </Box>

      {/* FAQ */}
      <Box component="section" sx={{ py: { xs: 6, md: 8 } }}>
        <Container maxWidth="md">
          <Typography variant="h4" component="h2" sx={{ fontWeight: 600, mb: 4 }}>
            {t('LandingPage.faq.title')}
          </Typography>
          {FAQS.map((item) => (
            <Accordion key={item} disableGutters elevation={0} sx={{ bgcolor: 'transparent' }}>
              <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                <Typography sx={{ fontWeight: 600 }}>
                  {t(`LandingPage.faq.items.${item}.q`)}
                </Typography>
              </AccordionSummary>
              <AccordionDetails>
                <Typography variant="body2" color="text.secondary">
                  {t(`LandingPage.faq.items.${item}.a`)}
                </Typography>
              </AccordionDetails>
            </Accordion>
          ))}
        </Container>
      </Box>

      {/* Honesty section — see the file docstring. */}
      <Box component="section" sx={{ py: { xs: 6, md: 8 }, bgcolor: 'action.hover' }}>
        <Container maxWidth="lg">
          <Paper variant="outlined" sx={{ p: { xs: 3, md: 4 }, bgcolor: 'background.paper' }}>
            <Typography variant="h5" component="h2" sx={{ fontWeight: 600, mb: 1 }}>
              {t('LandingPage.honesty.title')}
            </Typography>
            <Typography color="text.secondary" sx={{ mb: 2, maxWidth: 760 }}>
              {t('LandingPage.honesty.subtitle')}
            </Typography>
            <Stack component="ul" spacing={1} sx={{ pl: 3, m: 0 }}>
              {['mobile', 'knowledge', 'workflows'].map((item) => (
                <Typography key={item} component="li" variant="body2" color="text.secondary">
                  {t(`LandingPage.honesty.items.${item}`)}
                </Typography>
              ))}
            </Stack>
          </Paper>
        </Container>
      </Box>

      {/* Closing call to action */}
      <Box component="section" sx={{ py: { xs: 6, md: 10 } }}>
        <Container maxWidth="lg">
          <Stack spacing={3} sx={{ alignItems: 'flex-start' }}>
            <Typography variant="h4" component="h2" sx={{ fontWeight: 600 }}>
              {t('LandingPage.cta.title')}
            </Typography>
            <Typography color="text.secondary" sx={{ maxWidth: 640 }}>
              {t('LandingPage.cta.body')}
            </Typography>
            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
              <Button component={RouterLink} to="/register" size="large" variant="contained">
                {t('LandingPage.cta.primaryCta')}
              </Button>
              <Button component={RouterLink} to="/login" size="large" variant="outlined">
                {t('LandingPage.cta.secondaryCta')}
              </Button>
            </Stack>
          </Stack>
        </Container>
      </Box>

      <Divider />

      <Box component="footer" sx={{ py: 4 }}>
        <Container maxWidth="lg">
          <Stack
            direction={{ xs: 'column', sm: 'row' }}
            spacing={2}
            sx={{
              justifyContent: 'space-between',
              alignItems: { xs: 'flex-start', sm: 'center' },
            }}
          >
            <Typography variant="body2" color="text.secondary">
              {t('LandingPage.footer.copyright', { year: new Date().getFullYear() })}
            </Typography>
            <Stack direction="row" spacing={3}>
              <Link component={RouterLink} to="/login" variant="body2" underline="hover">
                {t('LandingPage.signIn')}
              </Link>
              <Link component={RouterLink} to="/register" variant="body2" underline="hover">
                {t('LandingPage.getStarted')}
              </Link>
              <Link component={RouterLink} to="/changelog" variant="body2" underline="hover">
                {t('LandingPage.footer.whatsNew')}
              </Link>
            </Stack>
          </Stack>
        </Container>
      </Box>
    </Box>
  )
}

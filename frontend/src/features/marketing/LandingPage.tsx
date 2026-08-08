import { Link as RouterLink } from 'react-router-dom'
import {
  AppBar,
  Box,
  Button,
  Container,
  Divider,
  Grid,
  Link,
  Paper,
  Stack,
  Toolbar,
  Typography,
} from '@mui/material'
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
      <Box component="section" sx={{ py: { xs: 6, md: 10 } }}>
        <Container maxWidth="lg">
          <Stack spacing={3} sx={{ maxWidth: 760 }}>
            <Typography variant="h2" component="h1" sx={{ fontWeight: 700, lineHeight: 1.15 }}>
              {t('LandingPage.hero.title')}
            </Typography>
            <Typography variant="h6" component="p" color="text.secondary" sx={{ fontWeight: 400 }}>
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
          </Stack>
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

import { useTranslation } from 'react-i18next'
import { Link as RouterLink, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import Alert from '@mui/material/Alert'
import Box from '@mui/material/Box'
import Button from '@mui/material/Button'
import CircularProgress from '@mui/material/CircularProgress'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'

import { apiClient } from '../../shared/api/client'

type Status = 'verified' | 'already_verified' | 'expired' | 'invalid'

/** The page the emailed link opens.
 *
 * Unauthenticated on purpose: the link arrives in an inbox and is
 * commonly opened on a different device from the one that signed up. */
export function VerifyEmailPage() {
  const { t } = useTranslation('auth')
  const [params] = useSearchParams()
  const token = params.get('token')

  const query = useQuery({
    queryKey: ['verify-email', token],
    // Only fires when there is a token — a missing one is decided
    // during render below, with no request and no effect.
    enabled: Boolean(token),
    // Consuming a token is a one-shot action, not a cacheable read. A
    // retry would report "already verified" for a link that had just
    // worked, and a refetch on window focus would do the same.
    retry: false,
    refetchOnWindowFocus: false,
    staleTime: Infinity,
    queryFn: async () => {
      const { data } = await apiClient.get<{ status: Status }>('/auth/verify-email', {
        params: { token },
      })
      return data.status
    },
  })

  const status: Status | 'error' | 'pending' = !token
    ? 'invalid'
    : query.isPending
      ? 'pending'
      : query.isError
        ? 'error'
        : query.data

  if (status === 'pending') {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', p: 8 }}>
        <CircularProgress />
      </Box>
    )
  }

  // "already verified" is a success, not a fault: somebody clicked the
  // link twice, or their mail client prefetched it.
  const succeeded = status === 'verified' || status === 'already_verified'

  return (
    <Stack spacing={3} sx={{ maxWidth: 460, mx: 'auto', p: 4, textAlign: 'center' }}>
      <Typography variant="h5" sx={{ fontWeight: 700 }}>
        {t('VerifyEmailPage.title')}
      </Typography>
      <Alert severity={succeeded ? 'success' : 'error'}>{t(`VerifyEmailPage.${status}`)}</Alert>
      <Button component={RouterLink} to="/" variant="contained">
        {succeeded ? t('VerifyEmailPage.continue') : t('VerifyEmailPage.backToSignIn')}
      </Button>
    </Stack>
  )
}

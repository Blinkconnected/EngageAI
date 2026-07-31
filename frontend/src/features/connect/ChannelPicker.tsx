import {
  Alert,
  Avatar,
  Box,
  Card,
  CardActionArea,
  Chip,
  CircularProgress,
  Dialog,
  DialogContent,
  DialogTitle,
  Stack,
  Typography,
} from '@mui/material'
import { useTranslation } from 'react-i18next'
import { useConnectCatalogQuery } from './api'
import { useConnectCopy, useOptionalCopy } from './copy'
import type { ConnectorProfile, LifecycleState } from './types'

/**
 * What can be connected, drawn entirely from the catalog.
 *
 * No channel list lives here. The server returns whichever connectors this
 * build ships, resolved against this installation, and every card is built
 * from that connector's own manifest — so a connector added tomorrow appears
 * with no change to this file.
 */

/** How each lifecycle state is badged.
 *
 * `production` and `available` get no badge at all: a chip on every card is a
 * chip nobody reads, and the states worth interrupting for are the ones that
 * change what a customer should expect.
 */
const BADGE: Partial<
  Record<LifecycleState, { color: 'info' | 'warning' | 'error' | 'default' }>
> = {
  preview: { color: 'info' },
  beta: { color: 'info' },
  deprecated: { color: 'warning' },
  maintenance: { color: 'warning' },
  disabled: { color: 'default' },
  end_of_life: { color: 'error' },
}

function ConnectorCard({
  profile,
  nameKey,
  descriptionKey,
  onPick,
}: {
  profile: ConnectorProfile
  nameKey: string
  descriptionKey: string
  onPick: () => void
}) {
  const { t } = useTranslation('connectSdk')
  const copy = useConnectCopy()
  const optional = useOptionalCopy()
  const badge = BADGE[profile.lifecycle]

  // Why it cannot be connected, in the customer's terms. The order matters:
  // "your Blink Engage is too old" is an administrator's problem and a
  // different sentence from "we have turned this off".
  const blockedReason = !profile.platform_supported
    ? t('picker.needsNewerPlatform')
    : profile.lifecycle === 'disabled'
      ? t('picker.turnedOff')
      : profile.lifecycle === 'maintenance'
        ? t('picker.temporarilyUnavailable')
        : profile.lifecycle === 'end_of_life'
          ? t('picker.noLongerAvailable')
          : null

  return (
    <Card
      variant="outlined"
      sx={{ opacity: profile.connectable ? 1 : 0.6, height: '100%' }}
    >
      <CardActionArea
        onClick={onPick}
        disabled={!profile.connectable}
        sx={{ p: 2, height: '100%', alignItems: 'flex-start' }}
      >
        <Stack direction="row" spacing={1.5} sx={{ alignItems: 'flex-start' }}>
          <Avatar
            variant="rounded"
            sx={{ bgcolor: 'action.hover', color: 'text.primary', width: 40, height: 40 }}
          >
            {copy(nameKey).slice(0, 1).toUpperCase()}
          </Avatar>
          <Box sx={{ minWidth: 0, flexGrow: 1 }}>
            <Stack direction="row" spacing={1} sx={{ alignItems: 'center', mb: 0.25 }}>
              <Typography variant="subtitle2" noWrap>
                {copy(nameKey)}
              </Typography>
              {badge && (
                <Chip
                  size="small"
                  color={badge.color}
                  variant="outlined"
                  label={t(`lifecycle.${profile.lifecycle}`)}
                />
              )}
            </Stack>
            <Typography
              variant="caption"
              color="text.secondary"
              sx={{
                display: '-webkit-box',
                WebkitLineClamp: 3,
                WebkitBoxOrient: 'vertical',
                overflow: 'hidden',
              }}
            >
              {blockedReason ?? optional(descriptionKey)}
            </Typography>
            {/* Its own line, and only where it changes what a customer should
                expect. A connector in preview is worth a sentence; one in
                production is not — and a caution that runs on from the
                description reads as part of it. */}
            {profile.connectable && profile.warns && (
              <Typography
                variant="caption"
                color="warning.main"
                sx={{ display: 'block', mt: 0.75 }}
              >
                {t(`lifecycle.warning.${profile.lifecycle}`, {
                  defaultValue: t('lifecycle.warning.generic'),
                })}
              </Typography>
            )}
          </Box>
        </Stack>
      </CardActionArea>
    </Card>
  )
}

export function ChannelPicker({
  open,
  onClose,
  onPick,
}: {
  open: boolean
  onClose: () => void
  onPick: (choice: { channelType?: string; templateKey?: string }) => void
}) {
  const { t } = useTranslation('connectSdk')
  const copy = useConnectCopy()
  const catalog = useConnectCatalogQuery({ enabled: open })

  const manifests = new Map(
    (catalog.data?.manifests ?? []).map((manifest) => [manifest.channel_type, manifest]),
  )

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>
        {t('picker.title')}
        <Typography variant="body2" color="text.secondary">
          {t('picker.subtitle')}
        </Typography>
      </DialogTitle>
      <DialogContent>
        {catalog.isPending && <CircularProgress size={24} />}
        {catalog.isError && <Alert severity="error">{t('picker.couldNotLoad')}</Alert>}

        {catalog.data && (
          <Stack spacing={3} sx={{ mt: 1 }}>
            {catalog.data.templates.length > 0 && (
              <Box>
                <Typography variant="subtitle2" sx={{ mb: 1 }}>
                  {t('picker.bundles')}
                </Typography>
                <Stack spacing={1}>
                  {catalog.data.templates.map((template) => (
                    <Card key={template.key} variant="outlined">
                      <CardActionArea
                        sx={{ p: 2 }}
                        onClick={() => onPick({ templateKey: template.key })}
                      >
                        <Stack
                          direction="row"
                          spacing={1}
                          sx={{ alignItems: 'center', mb: 0.25 }}
                        >
                          <Typography variant="subtitle2">
                            {copy(template.title_key)}
                          </Typography>
                          {template.recommended && (
                            <Chip
                              size="small"
                              color="primary"
                              label={t('picker.recommended')}
                            />
                          )}
                        </Stack>
                        <Typography variant="caption" color="text.secondary">
                          {copy(template.description_key)}
                        </Typography>
                      </CardActionArea>
                    </Card>
                  ))}
                </Stack>
              </Box>
            )}

            <Box>
              <Typography variant="subtitle2" sx={{ mb: 1 }}>
                {t('picker.oneChannel')}
              </Typography>
              <Box
                sx={{
                  display: 'grid',
                  gap: 1.5,
                  gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' },
                  alignItems: 'stretch',
                }}
              >
                {catalog.data.connectors.map((profile) => {
                  const manifest = manifests.get(profile.channel_type)
                  return (
                    <ConnectorCard
                      key={profile.channel_type}
                      profile={profile}
                      nameKey={manifest?.name_key ?? profile.channel_type}
                      descriptionKey={manifest?.description_key ?? ''}
                      onPick={() => onPick({ channelType: profile.channel_type })}
                    />
                  )
                })}
              </Box>
            </Box>
          </Stack>
        )}
      </DialogContent>
    </Dialog>
  )
}

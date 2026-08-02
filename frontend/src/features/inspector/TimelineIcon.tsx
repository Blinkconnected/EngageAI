import { memo } from 'react'
import { Box } from '@mui/material'
import PersonOutlineIcon from '@mui/icons-material/PersonOutlineOutlined'
import SupportAgentIcon from '@mui/icons-material/SupportAgent'
import SmartToyOutlinedIcon from '@mui/icons-material/SmartToyOutlined'
import GroupsOutlinedIcon from '@mui/icons-material/GroupsOutlined'
import AltRouteOutlinedIcon from '@mui/icons-material/AltRouteOutlined'
import ScheduleOutlinedIcon from '@mui/icons-material/ScheduleOutlined'
import GavelOutlinedIcon from '@mui/icons-material/GavelOutlined'
import SettingsOutlinedIcon from '@mui/icons-material/SettingsOutlined'
import type { ActorKind, Severity } from './types'

/** One icon per actor, so a reader can follow a single thread down the
 * timeline without reading every line — "where did AI act?" is answered by
 * scanning one column.
 *
 * The glyph is chosen by *actor* so a reader can follow one thread down the
 * column. The ring around it is the *backend's* severity — rendered, never
 * derived. Colouring a row red because the word "breach" appears in it would
 * be the UI inventing a judgement, and an invented flag is indistinguishable
 * from one the platform raised.
 */
const ICONS: Record<ActorKind, typeof PersonOutlineIcon> = {
  customer: PersonOutlineIcon,
  agent: SupportAgentIcon,
  ai: SmartToyOutlinedIcon,
  queue: GroupsOutlinedIcon,
  routing: AltRouteOutlinedIcon,
  sla: ScheduleOutlinedIcon,
  policy: GavelOutlinedIcon,
  system: SettingsOutlinedIcon,
}

const TINTS: Record<ActorKind, string> = {
  customer: 'info.main',
  agent: 'success.main',
  ai: 'secondary.main',
  queue: 'warning.main',
  routing: 'primary.main',
  sla: 'text.secondary',
  policy: 'text.secondary',
  system: 'text.disabled',
}

/** What each backend severity looks like. `info` deliberately has no ring:
 * most of a healthy conversation is info, and a badge on every row is a
 * badge on none. */
const SEVERITY_RING: Record<Severity, string | null> = {
  info: null,
  success: 'success.main',
  warning: 'warning.main',
  error: 'error.main',
  critical: 'error.dark',
}

export const TimelineIcon = memo(function TimelineIcon({
  actorKind,
  severity,
}: {
  actorKind: ActorKind
  severity: Severity
}) {
  const Icon = ICONS[actorKind] ?? SettingsOutlinedIcon
  const ring = SEVERITY_RING[severity] ?? null
  const tint = ring ?? TINTS[actorKind] ?? 'text.disabled'
  return (
    <Box
      aria-hidden
      sx={{
        width: 32,
        height: 32,
        flexShrink: 0,
        borderRadius: '50%',
        display: 'grid',
        placeItems: 'center',
        color: tint,
        bgcolor: 'background.paper',
        border: ring ? 2 : 1,
        borderColor: ring ?? 'divider',
      }}
    >
      <Icon fontSize="small" />
    </Box>
  )
})

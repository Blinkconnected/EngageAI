import { Link as RouterLink } from 'react-router-dom'
import {
  Avatar,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  List,
  ListItem,
  ListItemAvatar,
  ListItemText,
} from '@mui/material'
import { useTranslation } from 'react-i18next'
import { EmptyState } from '../../shared/components/EmptyState'
import { ErrorState } from '../../shared/components/ErrorState'
import { LoadingState } from '../../shared/components/LoadingState'
import { useRoleMembersQuery } from './api'
import type { Role } from './types'

export function RoleMembersDialog({ role, onClose }: { role: Role | null; onClose: () => void }) {
  const { t } = useTranslation('roles')
  const membersQuery = useRoleMembersQuery(role?.id ?? null)
  const membersLabel = role
    ? t('RoleMembersDialog.membersTitle', { name: role.name })
    : t('RoleMembersDialog.membersTitleFallback')

  return (
    <Dialog open={Boolean(role)} onClose={onClose} fullWidth maxWidth="xs">
      <DialogTitle>{membersLabel}</DialogTitle>
      <DialogContent>
        {membersQuery.isPending && <LoadingState label={t('RoleMembersDialog.loadingMembers')} />}
        {membersQuery.isError && (
          <ErrorState error={membersQuery.error} onRetry={() => membersQuery.refetch()} />
        )}
        {membersQuery.data && membersQuery.data.length === 0 && (
          <EmptyState
            title={t('RoleMembersDialog.emptyTitle')}
            description={t('RoleMembersDialog.emptyDescription')}
            action={
              <Button component={RouterLink} to="/agents" size="small" onClick={onClose}>
                {t('RoleMembersDialog.goToAgentsButton')}
              </Button>
            }
          />
        )}
        {membersQuery.data && membersQuery.data.length > 0 && (
          <List dense aria-label={membersLabel}>
            {membersQuery.data.map((member) => (
              <ListItem key={member.user_id} disableGutters>
                <ListItemAvatar>
                  <Avatar>{member.full_name.charAt(0).toUpperCase()}</Avatar>
                </ListItemAvatar>
                <ListItemText primary={member.full_name} secondary={member.email} />
              </ListItem>
            ))}
          </List>
        )}
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose}>{t('RoleMembersDialog.closeButton')}</Button>
      </DialogActions>
    </Dialog>
  )
}

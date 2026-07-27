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
import { EmptyState } from '../../shared/components/EmptyState'
import { ErrorState } from '../../shared/components/ErrorState'
import { LoadingState } from '../../shared/components/LoadingState'
import { useRoleMembersQuery } from './api'
import type { Role } from './types'

export function RoleMembersDialog({ role, onClose }: { role: Role | null; onClose: () => void }) {
  const membersQuery = useRoleMembersQuery(role?.id ?? null)

  return (
    <Dialog open={Boolean(role)} onClose={onClose} fullWidth maxWidth="xs">
      <DialogTitle>{role ? `${role.name} members` : 'Members'}</DialogTitle>
      <DialogContent>
        {membersQuery.isPending && <LoadingState label="Loading members…" />}
        {membersQuery.isError && (
          <ErrorState error={membersQuery.error} onRetry={() => membersQuery.refetch()} />
        )}
        {membersQuery.data && membersQuery.data.length === 0 && (
          <EmptyState title="No one has this role" description="Assign it from the Agents page." />
        )}
        {membersQuery.data && membersQuery.data.length > 0 && (
          <List dense aria-label={role ? `${role.name} members` : 'Members'}>
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
        <Button onClick={onClose}>Close</Button>
      </DialogActions>
    </Dialog>
  )
}

import {
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Button,
  List,
  ListItem,
  ListItemText,
  Typography,
} from '@mui/material'
import { EmptyState } from '../../shared/components/EmptyState'
import { useAllAgentsQuery } from '../agents/api'
import type { Department } from './types'

/** Read-only membership view — assignment itself stays on the Agent
 * form (its own "Department" picker is already the one place that
 * writes `Agent.department_id`), so this doesn't duplicate that
 * mutation path. */
export function DepartmentAgentsDialog({
  department,
  onClose,
}: {
  department: Department | null
  onClose: () => void
}) {
  const agentsQuery = useAllAgentsQuery()
  if (!department) return null

  const members = (agentsQuery.data ?? []).filter(
    (agent) => agent.department_id === department.id,
  )

  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>{department.name} — Agents</DialogTitle>
      <DialogContent>
        {members.length === 0 ? (
          <EmptyState
            title="No agents assigned"
            description="Assign agents to this department from the Agents page's Edit dialog."
          />
        ) : (
          <List dense>
            {members.map((agent) => (
              <ListItem key={agent.id} disableGutters>
                <ListItemText
                  primary={agent.full_name}
                  secondary={
                    <Typography variant="body2" color="text.secondary" component="span">
                      {agent.email}
                    </Typography>
                  }
                />
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

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
import { useTranslation } from 'react-i18next'
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
  const { t } = useTranslation('departments')
  const agentsQuery = useAllAgentsQuery()
  if (!department) return null

  const members = (agentsQuery.data ?? []).filter((agent) => agent.department_id === department.id)

  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>{t('DepartmentAgentsDialog.title', { name: department.name })}</DialogTitle>
      <DialogContent>
        {members.length === 0 ? (
          <EmptyState
            title={t('DepartmentAgentsDialog.emptyTitle')}
            description={t('DepartmentAgentsDialog.emptyDescription')}
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
        <Button onClick={onClose}>{t('DepartmentAgentsDialog.closeButton')}</Button>
      </DialogActions>
    </Dialog>
  )
}

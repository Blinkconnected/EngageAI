import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Alert,
  Avatar,
  Button,
  Card,
  CardContent,
  Chip,
  Divider,
  List,
  ListItem,
  ListItemAvatar,
  ListItemText,
  Stack,
  TextField,
  Typography,
} from '@mui/material'
import { extractErrorMessage } from '../../../shared/api/errors'
import { useAllAgentsQuery, useCreateAgentMutation } from '../../agents/api'
import { useAllDepartmentsQuery, useCreateDepartmentMutation } from '../../departments/api'
import { useCurrentUserQuery } from '../../session/api'

function OwnerSummary() {
  const { t } = useTranslation('onboarding')
  const { data: currentUser } = useCurrentUserQuery()
  if (!currentUser) return null

  return (
    <Card variant="outlined">
      <CardContent>
        <Stack direction="row" spacing={2} sx={{ alignItems: 'center' }}>
          <Avatar>{currentUser.full_name.charAt(0).toUpperCase()}</Avatar>
          <Stack sx={{ flexGrow: 1 }}>
            <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
              {currentUser.full_name}
            </Typography>
            <Typography variant="body2" color="text.secondary">
              {currentUser.email}
            </Typography>
          </Stack>
          {currentUser.is_company_owner && (
            <Chip label={t('TeamSetupStep.ownerChip')} color="primary" size="small" />
          )}
        </Stack>
      </CardContent>
    </Card>
  )
}

function InviteAgentForm() {
  const { t } = useTranslation('onboarding')
  const [email, setEmail] = useState('')
  const [fullName, setFullName] = useState('')
  const createMutation = useCreateAgentMutation()
  // The real, server-side agent roster — not a local success list, which
  // reset (misleadingly implying the invites never went through) every
  // time Back/Next remounted this step, since OnboardingWizardPage
  // renders steps conditionally.
  const agentsQuery = useAllAgentsQuery()

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    createMutation.mutate(
      { email, full_name: fullName },
      {
        onSuccess: () => {
          setEmail('')
          setFullName('')
        },
      },
    )
  }

  return (
    <Card variant="outlined">
      <CardContent>
        <Stack spacing={2} component="form" onSubmit={handleSubmit}>
          <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
            {t('TeamSetupStep.inviteAgentsTitle')}
          </Typography>
          <Typography variant="body2" color="text.secondary">
            {t('TeamSetupStep.inviteAgentsDescription')}
          </Typography>

          {createMutation.isError && (
            <Alert severity="error">{extractErrorMessage(createMutation.error)}</Alert>
          )}

          <Stack direction="row" spacing={2}>
            <TextField
              label={t('TeamSetupStep.fullNameLabel')}
              value={fullName}
              onChange={(event) => setFullName(event.target.value)}
              required
              fullWidth
            />
            <TextField
              label={t('TeamSetupStep.emailLabel')}
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              required
              fullWidth
            />
          </Stack>
          <Button
            type="submit"
            variant="outlined"
            disabled={createMutation.isPending}
            sx={{ alignSelf: 'flex-start' }}
          >
            {createMutation.isPending
              ? t('TeamSetupStep.invitingButton')
              : t('TeamSetupStep.inviteAgentButton')}
          </Button>

          {agentsQuery.data && agentsQuery.data.length > 0 && (
            <List dense subheader={t('TeamSetupStep.agentsOnTeamSubheader')}>
              {agentsQuery.data.map((agent) => (
                <ListItem key={agent.id}>
                  <ListItemAvatar>
                    <Avatar>{agent.full_name.charAt(0).toUpperCase()}</Avatar>
                  </ListItemAvatar>
                  <ListItemText primary={agent.full_name} secondary={agent.email} />
                </ListItem>
              ))}
            </List>
          )}
        </Stack>
      </CardContent>
    </Card>
  )
}

function CreateDepartmentForm() {
  const { t } = useTranslation('onboarding')
  const [name, setName] = useState('')
  const createMutation = useCreateDepartmentMutation()
  // Real, server-side departments — see InviteAgentForm's identical
  // reasoning for why a local-only success list is the wrong source here.
  const departmentsQuery = useAllDepartmentsQuery()

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    createMutation.mutate({ name, description: null }, { onSuccess: () => setName('') })
  }

  return (
    <Card variant="outlined">
      <CardContent>
        <Stack spacing={2} component="form" onSubmit={handleSubmit}>
          <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
            {t('TeamSetupStep.createDepartmentsTitle')}
          </Typography>

          {createMutation.isError && (
            <Alert severity="error">{extractErrorMessage(createMutation.error)}</Alert>
          )}

          <Stack direction="row" spacing={2}>
            <TextField
              label={t('TeamSetupStep.departmentNameLabel')}
              value={name}
              onChange={(event) => setName(event.target.value)}
              required
              fullWidth
            />
            <Button
              type="submit"
              variant="outlined"
              disabled={createMutation.isPending}
              sx={{ flexShrink: 0 }}
            >
              {createMutation.isPending
                ? t('TeamSetupStep.creatingButton')
                : t('TeamSetupStep.createButton')}
            </Button>
          </Stack>

          {departmentsQuery.data && departmentsQuery.data.length > 0 && (
            <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap' }}>
              {departmentsQuery.data.map((department) => (
                <Chip key={department.id} label={department.name} />
              ))}
            </Stack>
          )}
        </Stack>
      </CardContent>
    </Card>
  )
}

export function TeamSetupStep() {
  return (
    <Stack spacing={3}>
      <OwnerSummary />
      <Divider />
      <InviteAgentForm />
      <CreateDepartmentForm />
    </Stack>
  )
}

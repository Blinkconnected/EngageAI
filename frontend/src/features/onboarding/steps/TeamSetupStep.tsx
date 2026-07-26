import { useState } from 'react'
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
import { useCreateAgentMutation } from '../../agents/api'
import { useCreateDepartmentMutation } from '../../departments/api'
import { useCurrentUserQuery } from '../../session/api'

function OwnerSummary() {
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
          {currentUser.is_company_owner && <Chip label="Owner" color="primary" size="small" />}
        </Stack>
      </CardContent>
    </Card>
  )
}

function InviteAgentForm() {
  const [email, setEmail] = useState('')
  const [fullName, setFullName] = useState('')
  const [invited, setInvited] = useState<{ email: string; full_name: string }[]>([])
  const createMutation = useCreateAgentMutation()

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    createMutation.mutate(
      { email, full_name: fullName },
      {
        onSuccess: () => {
          setInvited((current) => [...current, { email, full_name: fullName }])
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
            Invite agents
          </Typography>
          <Typography variant="body2" color="text.secondary">
            They'll receive an email with a temporary password to sign in.
          </Typography>

          {createMutation.isError && (
            <Alert severity="error">{extractErrorMessage(createMutation.error)}</Alert>
          )}

          <Stack direction="row" spacing={2}>
            <TextField
              label="Full name"
              value={fullName}
              onChange={(event) => setFullName(event.target.value)}
              required
              fullWidth
            />
            <TextField
              label="Email"
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
            {createMutation.isPending ? 'Inviting…' : 'Invite agent'}
          </Button>

          {invited.length > 0 && (
            <List dense>
              {invited.map((agent) => (
                <ListItem key={agent.email}>
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
  const [name, setName] = useState('')
  const [created, setCreated] = useState<string[]>([])
  const createMutation = useCreateDepartmentMutation()

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    createMutation.mutate(
      { name, description: null },
      {
        onSuccess: () => {
          setCreated((current) => [...current, name])
          setName('')
        },
      },
    )
  }

  return (
    <Card variant="outlined">
      <CardContent>
        <Stack spacing={2} component="form" onSubmit={handleSubmit}>
          <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
            Create departments
          </Typography>

          {createMutation.isError && (
            <Alert severity="error">{extractErrorMessage(createMutation.error)}</Alert>
          )}

          <Stack direction="row" spacing={2}>
            <TextField
              label="Department name"
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
              {createMutation.isPending ? 'Creating…' : 'Create'}
            </Button>
          </Stack>

          {created.length > 0 && (
            <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap' }}>
              {created.map((departmentName) => (
                <Chip key={departmentName} label={departmentName} />
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

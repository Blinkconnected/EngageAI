import { useId, useMemo, useState, type FormEvent } from 'react'
import { Link as RouterLink, useParams } from 'react-router-dom'
import {
  Alert,
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  IconButton,
  MenuItem,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material'
import ForwardToInboxIcon from '@mui/icons-material/ForwardToInbox'
import HowToRegIcon from '@mui/icons-material/HowToReg'
import ManageAccountsIcon from '@mui/icons-material/ManageAccounts'
import PersonOffIcon from '@mui/icons-material/PersonOff'
import WorkspacePremiumIcon from '@mui/icons-material/WorkspacePremium'
import { useTranslation } from 'react-i18next'
import { EmptyState } from '../../shared/components/EmptyState'
import { ErrorState } from '../../shared/components/ErrorState'
import { LoadingState } from '../../shared/components/LoadingState'
import { extractErrorMessage } from '../../shared/api/errors'
import { usePlatformMeQuery } from './api'
import {
  useCompanyQuery,
  useCompanyUsersQuery,
  useResendVerificationMutation,
  useSetUserRoleMutation,
  useSetUserStatusMutation,
  useTransferOwnershipMutation,
} from './companyUsersApi'
import type { CompanyUser, CompanyUserRole } from './companyUsersApi'

type Translate = (key: string, options?: Record<string, unknown>) => string

/** The five things a platform operator may do to a tenant account.
 *
 * All of them either restore access or remove it; none of them *assumes*
 * it. There is deliberately no impersonation, no set-a-password, no
 * change-an-email and no delete — each of those turns administering an
 * account into taking it over, which is the line the platform tier does
 * not cross (docs/architecture/platform-admin.md). */
type ActionKind = 'deactivate' | 'reactivate' | 'verify' | 'role' | 'owner'

interface PendingAction {
  kind: ActionKind
  user: CompanyUser
}

/** The roles this company actually uses, taken from the accounts already
 * listed.
 *
 * The platform tier has no window into a tenant's role catalog and should
 * not grow one — reading it would be the first cross-tenant read that is
 * not an account fact. An operator can therefore move somebody between
 * roles the company already staffs, which is what an account recovery
 * needs; inventing a new role stays the company's own job. */
function rolesInUse(users: CompanyUser[]): CompanyUserRole[] {
  const byId = new Map<string, CompanyUserRole>()
  for (const user of users) {
    if (user.role) byId.set(user.role.id, user.role)
  }
  return [...byId.values()].sort((left, right) => left.name.localeCompare(right.name))
}

/** Why an action cannot be taken, or null when it can.
 *
 * Answered here rather than by letting the operator find out from a 409:
 * the rules below are the API's own refusals, and a button that fails is
 * a worse explanation than a disabled one that says why. */
function blockedReason(
  kind: ActionKind,
  user: CompanyUser,
  users: CompanyUser[],
  roles: CompanyUserRole[],
  t: Translate,
): string | null {
  switch (kind) {
    case 'deactivate':
      // A company with no owner has nobody who can manage its own roles,
      // so the last one cannot be locked out — not even by us.
      return user.is_company_owner && users.filter((item) => item.is_company_owner).length <= 1
        ? t('CompanyUsersPage.lastOwnerBlocked')
        : null
    case 'verify':
      return user.email_verified ? t('CompanyUsersPage.alreadyVerifiedBlocked') : null
    case 'role':
      if (user.is_company_owner) return t('CompanyUsersPage.ownerRoleBlocked')
      return roles.filter((role) => role.id !== user.role?.id).length === 0
        ? t('CompanyUsersPage.noOtherRoleBlocked')
        : null
    case 'owner':
      if (user.is_company_owner) return t('CompanyUsersPage.alreadyOwnerBlocked')
      // Handing the company to an account that cannot sign in leaves it
      // with an owner nobody can reach.
      return user.is_active ? null : t('CompanyUsersPage.inactiveOwnerBlocked')
    default:
      return null
  }
}

function formatDateTime(value: string | null, t: Translate): string {
  if (!value) return t('CompanyUsersPage.never')
  return new Date(value).toLocaleString()
}

function formatDate(value: string): string {
  return new Date(value).toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  })
}

/**
 * One company's user accounts, and the account actions a platform
 * operator may take on them.
 *
 * The screen states its own limits in copy rather than only in the API:
 * an operator sends a reset link *to the address on the account* and
 * never sees the password that results. That sentence is the difference
 * between restoring somebody's access and helping yourself to it, and it
 * belongs where the operator can read it.
 *
 * Every write asks for a reason first, because the reason is published on
 * the domain event and lands in the *tenant's own* audit log — the
 * customer can read what platform staff did to their accounts, and why.
 */
export function CompanyUsersPage() {
  const { t } = useTranslation('platform')
  const { companyId = '' } = useParams()

  const me = usePlatformMeQuery()
  // Unknown authority counts as read-only. Offering a control and then
  // withdrawing it invites a click that was never permitted; inside the
  // console this query has already resolved (PlatformRoute gates on it),
  // so in practice nothing flashes either way.
  const readOnly = me.data?.read_only ?? true

  const companyQuery = useCompanyQuery(companyId)
  const usersQuery = useCompanyUsersQuery(companyId)
  const users = useMemo(() => usersQuery.data?.items ?? [], [usersQuery.data])
  const roles = useMemo(() => rolesInUse(users), [users])

  const statusMutation = useSetUserStatusMutation(companyId)
  const verificationMutation = useResendVerificationMutation(companyId)
  const roleMutation = useSetUserRoleMutation(companyId)
  const ownerMutation = useTransferOwnershipMutation(companyId)

  const [pending, setPending] = useState<PendingAction | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const busy =
    statusMutation.isPending ||
    verificationMutation.isPending ||
    roleMutation.isPending ||
    ownerMutation.isPending

  function fail(mutationError: unknown) {
    setError(extractErrorMessage(mutationError, t('CompanyUsersPage.actionFailed')))
    setPending(null)
  }

  /** Routes one confirmed action to its endpoint. The reason travels with
   * every one of them — it is what the customer reads afterwards, so a
   * write that could omit it is not a write we make. */
  function confirmAction({ reason, roleId }: { reason: string; roleId: string }) {
    if (!pending) return
    setNotice(null)
    setError(null)
    const userId = pending.user.id

    switch (pending.kind) {
      case 'deactivate':
      case 'reactivate':
        statusMutation.mutate(
          { userId, isActive: pending.kind === 'reactivate', reason },
          { onSuccess: () => setPending(null), onError: fail },
        )
        return
      case 'verify':
        verificationMutation.mutate(
          { userId, reason },
          {
            onSuccess: (result) => {
              setNotice(t('CompanyUsersPage.verificationSent', { email: result.sent_to }))
              setPending(null)
            },
            onError: fail,
          },
        )
        return
      case 'role':
        roleMutation.mutate(
          { userId, roleId, reason },
          { onSuccess: () => setPending(null), onError: fail },
        )
        return
      case 'owner':
        ownerMutation.mutate(
          { userId, reason },
          { onSuccess: () => setPending(null), onError: fail },
        )
    }
  }

  const companyName = companyQuery.data?.name ?? ''

  return (
    <Stack spacing={2}>
      <Box>
        <Button component={RouterLink} to="/platform" size="small" sx={{ mb: 1 }}>
          {t('CompanyUsersPage.backToCompanies')}
        </Button>
        <Typography variant="h5" component="h1" sx={{ fontWeight: 700 }}>
          {companyName
            ? t('CompanyUsersPage.title', { companyName })
            : t('CompanyUsersPage.titleFallback')}
        </Typography>
        <Typography variant="body2" color="text.secondary">
          {t('CompanyUsersPage.subtitle')}
        </Typography>
      </Box>

      {me.isSuccess && readOnly && (
        <Alert severity="info">{t('CompanyUsersPage.readOnlyNotice')}</Alert>
      )}
      {notice && (
        <Alert severity="success" onClose={() => setNotice(null)}>
          {notice}
        </Alert>
      )}
      {error && (
        <Alert severity="error" onClose={() => setError(null)}>
          {error}
        </Alert>
      )}

      {usersQuery.isPending && <LoadingState label={t('CompanyUsersPage.loading')} />}
      {usersQuery.isError && (
        <ErrorState
          error={usersQuery.error}
          title={t('CompanyUsersPage.loadError')}
          onRetry={() => void usersQuery.refetch()}
        />
      )}

      {usersQuery.isSuccess &&
        (users.length === 0 ? (
          <EmptyState
            title={t('CompanyUsersPage.emptyTitle')}
            description={t('CompanyUsersPage.emptyDescription')}
          />
        ) : (
          <TableContainer>
            <Table size="small" aria-label={t('CompanyUsersPage.tableAriaLabel')}>
              <TableHead>
                <TableRow>
                  <TableCell>{t('CompanyUsersPage.columnName')}</TableCell>
                  <TableCell>{t('CompanyUsersPage.columnEmail')}</TableCell>
                  <TableCell>{t('CompanyUsersPage.columnRole')}</TableCell>
                  <TableCell>{t('CompanyUsersPage.columnStatus')}</TableCell>
                  <TableCell>{t('CompanyUsersPage.columnOwner')}</TableCell>
                  <TableCell>{t('CompanyUsersPage.columnVerified')}</TableCell>
                  <TableCell>{t('CompanyUsersPage.columnLastSignIn')}</TableCell>
                  <TableCell>{t('CompanyUsersPage.columnCreated')}</TableCell>
                  {/* A read-only operator gets no column of dead buttons —
                      the list is the whole point of that tier. */}
                  {!readOnly && (
                    <TableCell align="right">{t('CompanyUsersPage.columnActions')}</TableCell>
                  )}
                </TableRow>
              </TableHead>
              <TableBody>
                {users.map((user) => (
                  <TableRow key={user.id} hover>
                    <TableCell>{user.full_name}</TableCell>
                    <TableCell>{user.email}</TableCell>
                    <TableCell>{user.role?.name ?? t('CompanyUsersPage.noRole')}</TableCell>
                    <TableCell>
                      <Chip
                        size="small"
                        color={user.is_active ? 'success' : 'default'}
                        label={
                          user.is_active
                            ? t('CompanyUsersPage.statusActive')
                            : t('CompanyUsersPage.statusInactive')
                        }
                      />
                    </TableCell>
                    <TableCell>
                      {user.is_company_owner ? (
                        <Chip size="small" color="primary" label={t('CompanyUsersPage.ownerYes')} />
                      ) : (
                        '—'
                      )}
                    </TableCell>
                    <TableCell>
                      {user.email_verified
                        ? t('CompanyUsersPage.verifiedYes')
                        : t('CompanyUsersPage.verifiedNo')}
                    </TableCell>
                    <TableCell>{formatDateTime(user.last_login_at, t)}</TableCell>
                    <TableCell>{formatDate(user.created_at)}</TableCell>
                    {!readOnly && (
                      <TableCell align="right">
                        <UserActions
                          user={user}
                          users={users}
                          roles={roles}
                          onPick={(kind) => setPending({ kind, user })}
                        />
                      </TableCell>
                    )}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        ))}

      {pending && (
        <UserActionDialog
          action={pending}
          roles={roles}
          busy={busy}
          onConfirm={confirmAction}
          onClose={() => setPending(null)}
        />
      )}
    </Stack>
  )
}

/** The row's actions, each labelled with what it will actually do.
 *
 * "Send a reset link to ada@acme.com" and "Reset password" are different
 * sentences, and only the first tells an operator what is about to land in
 * somebody's inbox — so the address, not a generic verb, is the label. */
function UserActions({
  user,
  users,
  roles,
  onPick,
}: {
  user: CompanyUser
  users: CompanyUser[]
  roles: CompanyUserRole[]
  onPick: (kind: ActionKind) => void
}) {
  const { t } = useTranslation('platform')
  const statusKind: ActionKind = user.is_active ? 'deactivate' : 'reactivate'
  const statusBlocked = blockedReason(statusKind, user, users, roles, t)
  const verifyBlocked = blockedReason('verify', user, users, roles, t)
  const roleBlocked = blockedReason('role', user, users, roles, t)
  const ownerBlocked = blockedReason('owner', user, users, roles, t)

  return (
    <Stack direction="row" spacing={0.5} sx={{ justifyContent: 'flex-end' }}>
      <Tooltip
        title={
          statusBlocked ??
          (user.is_active
            ? t('CompanyUsersPage.deactivateTooltip')
            : t('CompanyUsersPage.reactivateTooltip'))
        }
      >
        <span>
          <IconButton
            size="small"
            disabled={statusBlocked !== null}
            onClick={() => onPick(statusKind)}
            aria-label={t(
              user.is_active
                ? 'CompanyUsersPage.deactivateAriaLabel'
                : 'CompanyUsersPage.reactivateAriaLabel',
              { name: user.full_name },
            )}
          >
            {user.is_active ? (
              <PersonOffIcon fontSize="small" />
            ) : (
              <HowToRegIcon fontSize="small" />
            )}
          </IconButton>
        </span>
      </Tooltip>

      {/* No password-reset action, deliberately. The product has no
          password-reset flow — no token model, no issuer, no consume
          endpoint — so there is nothing to call. A button here would 404
          while telling an operator a mail had gone out, and they would
          stop chasing an account that is still locked out. */}

      <Tooltip title={verifyBlocked ?? t('CompanyUsersPage.verifyTooltip', { email: user.email })}>
        <span>
          <IconButton
            size="small"
            disabled={verifyBlocked !== null}
            onClick={() => onPick('verify')}
            aria-label={t('CompanyUsersPage.verifyAriaLabel', { email: user.email })}
          >
            <ForwardToInboxIcon fontSize="small" />
          </IconButton>
        </span>
      </Tooltip>

      <Tooltip title={roleBlocked ?? t('CompanyUsersPage.roleTooltip')}>
        <span>
          <IconButton
            size="small"
            disabled={roleBlocked !== null}
            onClick={() => onPick('role')}
            aria-label={t('CompanyUsersPage.roleAriaLabel', { name: user.full_name })}
          >
            <ManageAccountsIcon fontSize="small" />
          </IconButton>
        </span>
      </Tooltip>

      <Tooltip title={ownerBlocked ?? t('CompanyUsersPage.ownerTooltip')}>
        <span>
          <IconButton
            size="small"
            disabled={ownerBlocked !== null}
            onClick={() => onPick('owner')}
            aria-label={t('CompanyUsersPage.ownerAriaLabel', { name: user.full_name })}
          >
            <WorkspacePremiumIcon fontSize="small" />
          </IconButton>
        </span>
      </Tooltip>
    </Stack>
  )
}

interface DialogCopy {
  title: string
  body: string
  confirm: string
  colour: 'primary' | 'error'
}

function dialogCopy(kind: ActionKind, user: CompanyUser, t: Translate): DialogCopy {
  const name = user.full_name
  const email = user.email
  switch (kind) {
    case 'deactivate':
      return {
        title: t('CompanyUsersPage.deactivateTitle', { name }),
        body: t('CompanyUsersPage.deactivateBody', { name }),
        confirm: t('CompanyUsersPage.deactivateConfirm'),
        colour: 'error',
      }
    case 'reactivate':
      return {
        title: t('CompanyUsersPage.reactivateTitle', { name }),
        body: t('CompanyUsersPage.reactivateBody', { name }),
        confirm: t('CompanyUsersPage.reactivateConfirm'),
        colour: 'primary',
      }
    case 'verify':
      return {
        title: t('CompanyUsersPage.verifyTitle', { email }),
        body: t('CompanyUsersPage.verifyBody', { email }),
        confirm: t('CompanyUsersPage.verifyConfirm'),
        colour: 'primary',
      }
    case 'role':
      return {
        title: t('CompanyUsersPage.roleTitle', { name }),
        body: t('CompanyUsersPage.roleBody'),
        confirm: t('CompanyUsersPage.roleConfirm'),
        colour: 'primary',
      }
    case 'owner':
      return {
        title: t('CompanyUsersPage.ownerTitle', { name }),
        body: t('CompanyUsersPage.ownerBody', { name }),
        confirm: t('CompanyUsersPage.ownerConfirm'),
        colour: 'primary',
      }
  }
}

/**
 * Confirmation and reason in one step.
 *
 * The reason is not a field bolted onto the end: it is what the customer
 * will read in their own audit log next to the operator's name, so the
 * action cannot be confirmed without it. Asking afterwards would make it
 * paperwork; asking here makes it the justification.
 */
function UserActionDialog({
  action,
  roles,
  busy,
  onConfirm,
  onClose,
}: {
  action: PendingAction
  roles: CompanyUserRole[]
  busy: boolean
  onConfirm: (input: { reason: string; roleId: string }) => void
  onClose: () => void
}) {
  const { t } = useTranslation('platform')
  const titleId = useId()
  const [reason, setReason] = useState('')
  const [roleId, setRoleId] = useState('')

  const copy = dialogCopy(action.kind, action.user, t)
  const needsRole = action.kind === 'role'
  // Moving somebody to the role they already hold changes nothing, so it
  // is not offered as a destination.
  const options = roles.filter((role) => role.id !== action.user.role?.id)
  const ready = reason.trim().length > 0 && (!needsRole || roleId !== '')

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    if (!ready || busy) return
    onConfirm({ reason: reason.trim(), roleId })
  }

  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="sm" aria-labelledby={titleId}>
      <DialogTitle id={titleId}>{copy.title}</DialogTitle>
      <form onSubmit={handleSubmit}>
        <DialogContent>
          <Stack spacing={2} sx={{ pt: 1 }}>
            <Typography variant="body2">{copy.body}</Typography>
            {needsRole && (
              <TextField
                select
                required
                label={t('CompanyUsersPage.roleFieldLabel')}
                value={roleId}
                onChange={(event) => setRoleId(event.target.value)}
                helperText={t('CompanyUsersPage.roleFieldHelp')}
              >
                {options.map((role) => (
                  <MenuItem key={role.id} value={role.id}>
                    {role.name}
                  </MenuItem>
                ))}
              </TextField>
            )}
            <TextField
              required
              fullWidth
              multiline
              minRows={2}
              label={t('CompanyUsersPage.reasonLabel')}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              helperText={t('CompanyUsersPage.reasonHelp')}
            />
          </Stack>
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2 }}>
          <Button color="inherit" onClick={onClose} disabled={busy}>
            {t('CompanyUsersPage.cancel')}
          </Button>
          <Button type="submit" variant="contained" color={copy.colour} disabled={!ready || busy}>
            {copy.confirm}
          </Button>
        </DialogActions>
      </form>
    </Dialog>
  )
}

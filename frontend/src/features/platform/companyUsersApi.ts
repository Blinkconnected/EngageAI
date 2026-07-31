import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../../shared/api/client'
import type { CompanyOverview } from './types'

/** A role as it appears on one of the company's users. Just enough to
 * name it and to reassign it — the permission set behind it belongs to
 * the company's own Roles page, not to a platform operator. */
export interface CompanyUserRole {
  id: string
  name: string
}

/** One user of a tenant company, as a platform operator may see them.
 *
 * Mirrors the backend's company-user response, and deliberately carries
 * account facts only: who the person is and what state their access is
 * in. Nothing here is tenant content — no conversations, customers or
 * messages — which is the promise the whole platform tier is built
 * around (docs/architecture/platform-admin.md). */
export interface CompanyUser {
  id: string
  email: string
  full_name: string
  is_active: boolean
  is_company_owner: boolean
  email_verified: boolean
  last_login_at: string | null
  created_at: string
  role: CompanyUserRole | null
}

/** The whole list in one response — the API does not paginate it, because
 * a company's staff list is small and an operator acting on an account
 * needs to see every account to know it is the last owner. */
export interface CompanyUserList {
  items: CompanyUser[]
  total: number
}

/** What a mail action reports back: the address it actually went to.
 *
 * The operator names no address; the server answers with the one on the
 * account. Showing it is what makes "a link to their own inbox, not
 * yours" checkable rather than merely claimed. */
export interface MailSentResult {
  sent_to: string
}

const companyUsersKey = (companyId: string) => ['platform', 'companies', companyId, 'users']
const companyKey = (companyId: string) => ['platform', 'companies', companyId, 'overview']

/** The company itself, so the screen can say whose accounts these are.
 *
 * A separate request rather than routing state: the page is reachable by
 * a pasted URL, and a header that reads "this company" tells an operator
 * nothing about which customer they are about to act on. */
export function useCompanyQuery(companyId: string) {
  return useQuery({
    queryKey: companyKey(companyId),
    queryFn: async () => {
      const { data } = await apiClient.get<CompanyOverview>(`/platform/companies/${companyId}`)
      return data
    },
  })
}

export function useCompanyUsersQuery(companyId: string) {
  return useQuery({
    queryKey: companyUsersKey(companyId),
    queryFn: async () => {
      const { data } = await apiClient.get<CompanyUserList>(
        `/platform/companies/${companyId}/users`,
      )
      return data
    },
  })
}

/** Every write below takes a **required** `reason`, typed non-optional so
 * a call without one does not compile. The customer reads it in their own
 * audit log, and six months later it is the only explanation anybody has
 * for why platform staff touched their account.
 *
 * Each one invalidates the company's user list rather than seeding the
 * cache from the response: a status change or an ownership transfer moves
 * state on *another* row too (the previous owner), so only a refetch
 * describes the company correctly afterwards. */

export function useSetUserStatusMutation(companyId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (input: { userId: string; isActive: boolean; reason: string }) => {
      const { data } = await apiClient.patch<CompanyUser>(
        `/platform/companies/${companyId}/users/${input.userId}/status`,
        { is_active: input.isActive, reason: input.reason },
      )
      return data
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: companyUsersKey(companyId) }),
  })
}

/* There is deliberately no password-reset call here.
 *
 * The product has no password-reset flow at all — no token model, no
 * issuer, no consume endpoint — so there is nothing for the console to
 * call, and the platform route does not exist. A button that posted to it
 * would 404 while telling an operator a mail had gone out, which is worse
 * than the action being absent: they would stop chasing it.
 *
 * The one existing "reset" in the codebase has the caller choose the new
 * password, which is the account-takeover primitive this whole surface is
 * built to avoid. When a self-service reset ships, this is where the
 * console hooks into it — reusing that issuer, never a second one. */

export function useResendVerificationMutation(companyId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (input: { userId: string; reason: string }) => {
      const { data } = await apiClient.post<MailSentResult>(
        `/platform/companies/${companyId}/users/${input.userId}/verification`,
        { reason: input.reason },
      )
      return data
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: companyUsersKey(companyId) }),
  })
}

export function useSetUserRoleMutation(companyId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (input: { userId: string; roleId: string; reason: string }) => {
      const { data } = await apiClient.put<CompanyUser>(
        `/platform/companies/${companyId}/users/${input.userId}/role`,
        { role_id: input.roleId, reason: input.reason },
      )
      return data
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: companyUsersKey(companyId) }),
  })
}

/** Moves ownership to another user of the same company.
 *
 * Posted to the company rather than to either user: exactly one account
 * can hold it, so this is a change to the company, and addressing it to
 * the incoming owner is what keeps two concurrent transfers from both
 * appearing to succeed. */
export function useTransferOwnershipMutation(companyId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (input: { userId: string; reason: string }) => {
      const { data } = await apiClient.post<CompanyUser>(`/platform/companies/${companyId}/owner`, {
        user_id: input.userId,
        reason: input.reason,
      })
      return data
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: companyUsersKey(companyId) }),
  })
}

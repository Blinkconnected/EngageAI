import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../../shared/api/client'
import type {
  AgentRole,
  Permission,
  Role,
  RoleCreateRequest,
  RoleMember,
  RoleUpdateRequest,
} from './types'

const ROLES_LIST_KEY = ['roles', 'list']
const PERMISSIONS_KEY = ['roles', 'permissions']

async function fetchRoles(): Promise<Role[]> {
  const { data } = await apiClient.get<Role[]>('/roles')
  return data
}

async function fetchPermissions(): Promise<Permission[]> {
  const { data } = await apiClient.get<Permission[]>('/permissions')
  return data
}

async function createRole(payload: RoleCreateRequest): Promise<Role> {
  const { data } = await apiClient.post<Role>('/roles', payload)
  return data
}

async function updateRole(roleId: string, payload: RoleUpdateRequest): Promise<Role> {
  const { data } = await apiClient.patch<Role>(`/roles/${roleId}`, payload)
  return data
}

async function deleteRole(roleId: string): Promise<void> {
  await apiClient.delete(`/roles/${roleId}`)
}

async function fetchRoleMembers(roleId: string): Promise<RoleMember[]> {
  const { data } = await apiClient.get<RoleMember[]>(`/roles/${roleId}/members`)
  return data
}

async function fetchAgentRole(agentId: string): Promise<AgentRole> {
  const { data } = await apiClient.get<AgentRole>(`/agents/${agentId}/role`)
  return data
}

async function updateAgentRole(agentId: string, roleId: string): Promise<AgentRole> {
  const { data } = await apiClient.put<AgentRole>(`/agents/${agentId}/role`, { role_id: roleId })
  return data
}

/** Not paginated — like Queues & Routing's own rules list, a company's
 * role count (the 3 seeded system roles plus however many custom ones an
 * Owner defines) is small and meant to be seen as a whole. */
export function useRolesQuery() {
  return useQuery({ queryKey: ROLES_LIST_KEY, queryFn: fetchRoles })
}

/** The static permission catalog — every role's checklist of possible
 * grants. Long `staleTime` since this never changes at runtime. */
export function usePermissionsQuery() {
  return useQuery({ queryKey: PERMISSIONS_KEY, queryFn: fetchPermissions, staleTime: 60_000 })
}

function invalidateRoles(queryClient: ReturnType<typeof useQueryClient>) {
  queryClient.invalidateQueries({ queryKey: ROLES_LIST_KEY })
}

export function useCreateRoleMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: createRole,
    onSuccess: () => invalidateRoles(queryClient),
  })
}

export function useUpdateRoleMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ roleId, payload }: { roleId: string; payload: RoleUpdateRequest }) =>
      updateRole(roleId, payload),
    onSuccess: () => invalidateRoles(queryClient),
  })
}

export function useDeleteRoleMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: deleteRole,
    onSuccess: () => invalidateRoles(queryClient),
  })
}

export function useRoleMembersQuery(roleId: string | null) {
  return useQuery({
    queryKey: ['roles', 'members', roleId],
    queryFn: () => fetchRoleMembers(roleId as string),
    enabled: roleId !== null,
  })
}

/** On-demand only — fetched when a "Change role" dialog opens for a
 * specific agent, not baked into the main Agents list (mirrors the
 * backend's own `GET /agents/{id}/role` being a separate endpoint from
 * `AgentResponse`). */
export function useAgentRoleQuery(agentId: string | null) {
  return useQuery({
    queryKey: ['agents', 'role', agentId],
    queryFn: () => fetchAgentRole(agentId as string),
    enabled: agentId !== null,
  })
}

export function useUpdateAgentRoleMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ agentId, roleId }: { agentId: string; roleId: string }) =>
      updateAgentRole(agentId, roleId),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: ['agents', 'role', variables.agentId] })
      invalidateRoles(queryClient)
    },
  })
}

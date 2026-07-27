import { http, HttpResponse } from 'msw'
import { API_BASE_URL } from '../apiBaseUrl'
import type {
  AgentRole,
  Permission,
  Role,
  RoleCreateRequest,
  RoleMember,
  RoleUpdateRequest,
} from '../../features/roles/types'
import { MOCK_USER } from './auth'

// Mirrors the shape (not necessarily every entry) of the backend's
// domain.rbac.PERMISSIONS catalog — enough breadth for the checklist UI
// to exercise grouping/selection realistically without needing to stay
// byte-for-byte in sync with the real 30-entry list.
const SEED_PERMISSIONS: Permission[] = [
  { code: 'company.manage', description: 'Manage company profile and settings' },
  { code: 'users.read', description: 'View users in the company' },
  { code: 'users.manage', description: 'Invite, edit, deactivate users' },
  { code: 'roles.manage', description: 'Create/edit/delete roles and their permissions' },
  { code: 'departments.read', description: 'View departments' },
  { code: 'departments.manage', description: 'Create/edit/delete departments' },
  { code: 'agents.read', description: 'View agent profiles' },
  { code: 'agents.manage', description: 'Create/edit/delete agent profiles' },
  { code: 'customers.read', description: 'View customer profiles' },
  { code: 'customers.manage', description: 'Create/edit/merge/delete customer profiles' },
  { code: 'conversations.read', description: 'View conversations' },
  { code: 'conversations.manage', description: 'Reply, assign, close conversations' },
  { code: 'conversations.delete', description: 'Permanently delete conversations' },
  {
    code: 'conversations.transfer',
    description: 'Transfer conversations to another agent or department',
  },
  { code: 'reports.read', description: 'View reports and dashboards' },
  { code: 'audit_logs.read', description: 'View audit logs' },
  { code: 'channels.read', description: 'View channel configurations' },
  { code: 'channels.manage', description: 'Create/edit/delete channel configurations' },
  { code: 'queues.read', description: 'View queues, required skills, and routing rules' },
  {
    code: 'queues.manage',
    description: 'Create/edit/delete queues, required skills, and routing rules',
  },
  { code: 'ai.use', description: 'Use AI Engine features' },
  { code: 'erp.manage', description: 'Configure the ERPNext connection and trigger manual sync/pull' },
]

const ALL_CODES = SEED_PERMISSIONS.map((permission) => permission.code)

const SEED_ROLES: Role[] = [
  {
    id: 'role-owner',
    name: 'Owner',
    description: null,
    is_system: true,
    permission_codes: ALL_CODES,
    member_count: 1,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  },
  {
    id: 'role-admin',
    name: 'Admin',
    description: null,
    is_system: true,
    permission_codes: ALL_CODES.filter((code) => code !== 'roles.manage'),
    member_count: 0,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  },
  {
    id: 'role-agent',
    name: 'Agent',
    description: null,
    is_system: true,
    permission_codes: [
      'departments.read',
      'agents.read',
      'customers.read',
      'customers.manage',
      'conversations.read',
      'conversations.manage',
      'reports.read',
      'queues.read',
      'ai.use',
    ],
    member_count: 1,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  },
]

// agent_id -> role_id. Keyed by agent id (not user id) since that's all
// the frontend's `/agents/:agentId/role` contract ever deals in — see
// features/roles/api.ts.
const SEED_AGENT_ROLES: Record<string, string> = {
  a1: 'role-agent',
  'a-self': 'role-owner',
}

// Minimal name/email lookup for the two seeded agents above (mirrors
// mocks/handlers/agents.ts's SEED_AGENTS without importing its private,
// mutable `agents` array) — used only to render a realistic members
// list. Any other agent id (e.g. one created mid-test) still works via
// the placeholder fallback in the members handler below.
const AGENT_DIRECTORY: Record<string, { user_id: string; full_name: string; email: string }> = {
  a1: { user_id: 'u1', full_name: 'Grace Hopper', email: 'grace@example.com' },
  'a-self': { user_id: MOCK_USER.id, full_name: MOCK_USER.full_name, email: MOCK_USER.email },
}

let roles: Role[] = [...SEED_ROLES]
let agentRoles: Record<string, string> = { ...SEED_AGENT_ROLES }
let nextRoleId = 100

export function resetRolesMock() {
  roles = [...SEED_ROLES]
  agentRoles = { ...SEED_AGENT_ROLES }
  nextRoleId = 100
}

function memberCount(roleId: string): number {
  return Object.values(agentRoles).filter((id) => id === roleId).length
}

function withComputedMemberCount(role: Role): Role {
  return { ...role, member_count: memberCount(role.id) }
}

export const rolesHandlers = [
  http.get(`${API_BASE_URL}/permissions`, () => HttpResponse.json(SEED_PERMISSIONS)),

  http.get(`${API_BASE_URL}/roles`, () =>
    HttpResponse.json(roles.map(withComputedMemberCount)),
  ),

  http.post(`${API_BASE_URL}/roles`, async ({ request }) => {
    const payload = (await request.json()) as RoleCreateRequest
    if (roles.some((role) => role.name === payload.name)) {
      return HttpResponse.json({ detail: 'A role with this name already exists' }, { status: 409 })
    }
    const created: Role = {
      id: `role${nextRoleId}`,
      name: payload.name,
      description: payload.description ?? null,
      is_system: false,
      permission_codes: [...payload.permission_codes].sort(),
      member_count: 0,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    }
    nextRoleId += 1
    roles = [...roles, created]
    return HttpResponse.json(created, { status: 201 })
  }),

  http.get(`${API_BASE_URL}/roles/:roleId`, ({ params }) => {
    const role = roles.find((item) => item.id === params.roleId)
    if (!role) return HttpResponse.json({ detail: 'Not found' }, { status: 404 })
    return HttpResponse.json(withComputedMemberCount(role))
  }),

  http.patch(`${API_BASE_URL}/roles/:roleId`, async ({ request, params }) => {
    const payload = (await request.json()) as RoleUpdateRequest
    const index = roles.findIndex((role) => role.id === params.roleId)
    if (index === -1) return HttpResponse.json({ detail: 'Not found' }, { status: 404 })
    const existing = roles[index]

    if (payload.name !== undefined && payload.name !== existing.name && existing.is_system) {
      return HttpResponse.json({ detail: "A system role's name can't be changed" }, { status: 400 })
    }
    if (payload.permission_codes !== undefined && existing.is_system && existing.name === 'Owner') {
      return HttpResponse.json(
        { detail: "The Owner role's permissions can't be changed" },
        { status: 400 },
      )
    }

    const updated: Role = {
      ...existing,
      ...(payload.name !== undefined ? { name: payload.name } : {}),
      ...(payload.description !== undefined ? { description: payload.description } : {}),
      ...(payload.permission_codes !== undefined
        ? { permission_codes: [...payload.permission_codes].sort() }
        : {}),
    }
    roles = [...roles.slice(0, index), updated, ...roles.slice(index + 1)]
    return HttpResponse.json(withComputedMemberCount(updated))
  }),

  http.delete(`${API_BASE_URL}/roles/:roleId`, ({ params }) => {
    const role = roles.find((item) => item.id === params.roleId)
    if (!role) return HttpResponse.json({ detail: 'Not found' }, { status: 404 })
    if (role.is_system) {
      return HttpResponse.json({ detail: "System roles can't be deleted" }, { status: 400 })
    }
    if (memberCount(role.id) > 0) {
      return HttpResponse.json({ detail: 'Role still has members' }, { status: 400 })
    }
    roles = roles.filter((item) => item.id !== role.id)
    return new HttpResponse(null, { status: 204 })
  }),

  http.get(`${API_BASE_URL}/roles/:roleId/members`, ({ params }) => {
    const roleId = params.roleId as string
    const members: RoleMember[] = Object.entries(agentRoles)
      .filter(([, assignedRoleId]) => assignedRoleId === roleId)
      .map(([agentId]) => {
        const known = AGENT_DIRECTORY[agentId]
        return known ?? { user_id: `u-${agentId}`, full_name: `Agent ${agentId}`, email: '—' }
      })
    return HttpResponse.json(members)
  }),

  http.get(`${API_BASE_URL}/agents/:agentId/role`, ({ params }) => {
    const agentId = params.agentId as string
    const roleId = agentRoles[agentId] ?? 'role-agent'
    const role = roles.find((item) => item.id === roleId)
    const body: AgentRole = { role_id: roleId, role_name: role?.name ?? 'Agent' }
    return HttpResponse.json(body)
  }),

  http.put(`${API_BASE_URL}/agents/:agentId/role`, async ({ request, params }) => {
    const agentId = params.agentId as string
    const payload = (await request.json()) as { role_id: string }
    const role = roles.find((item) => item.id === payload.role_id)
    if (!role) return HttpResponse.json({ detail: 'Not found' }, { status: 404 })
    agentRoles = { ...agentRoles, [agentId]: role.id }
    const body: AgentRole = { role_id: role.id, role_name: role.name }
    return HttpResponse.json(body)
  }),
]

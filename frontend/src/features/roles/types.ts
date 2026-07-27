/** Matches the backend's `PermissionResponse` — the static catalog every
 * role's `permission_codes` is built from (see domain.rbac.PERMISSIONS). */
export interface Permission {
  code: string
  description: string
}

/** Matches the backend's `RoleResponse`. */
export interface Role {
  id: string
  name: string
  description: string | null
  is_system: boolean
  permission_codes: string[]
  member_count: number
  created_at: string
  updated_at: string
}

export interface RoleCreateRequest {
  name: string
  description?: string | null
  permission_codes: string[]
}

export interface RoleUpdateRequest {
  name?: string
  description?: string | null
  permission_codes?: string[]
}

/** Matches the backend's `RoleMemberResponse`. */
export interface RoleMember {
  user_id: string
  full_name: string
  email: string
}

/** Matches the backend's `AgentRoleResponse`. */
export interface AgentRole {
  role_id: string
  role_name: string
}

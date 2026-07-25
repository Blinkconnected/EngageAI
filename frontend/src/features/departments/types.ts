/** Matches the backend's `DepartmentResponse`. */
export interface Department {
  id: string
  name: string
  description: string | null
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface DepartmentCreateRequest {
  name: string
  description?: string | null
}

export interface DepartmentUpdateRequest {
  name?: string
  description?: string | null
  is_active?: boolean
}

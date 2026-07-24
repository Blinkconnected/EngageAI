/** Matches the backend's `DepartmentResponse`. */
export interface Department {
  id: string
  name: string
  description: string | null
  is_active: boolean
  created_at: string
  updated_at: string
}

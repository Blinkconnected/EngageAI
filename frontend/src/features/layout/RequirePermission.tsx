import type { ReactNode } from 'react'
import { Navigate } from 'react-router-dom'
import { usePermissions } from '../../shared/hooks/usePermissions'

export function RequirePermission({
  permission,
  children,
}: {
  permission: string
  children: ReactNode
}) {
  const { hasPermission } = usePermissions()

  if (!hasPermission(permission)) {
    return <Navigate to="/403" replace />
  }

  return children
}

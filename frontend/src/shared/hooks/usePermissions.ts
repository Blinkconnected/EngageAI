import { useCurrentUserQuery } from '../../features/session/api'

export function usePermissions() {
  const { data } = useCurrentUserQuery()
  const permissions = data?.permissions ?? []

  return {
    permissions,
    hasPermission: (code: string) => permissions.includes(code),
    hasAnyPermission: (codes: string[]) => codes.some((code) => permissions.includes(code)),
  }
}

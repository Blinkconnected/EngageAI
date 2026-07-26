import type { ReactNode } from 'react'
import { Navigate } from 'react-router-dom'
import { useCompanyQuery, useIsErpEnabled } from '../company/api'

/** Route guard for `/erp-configs` — ERP must be completely hidden
 * (including this direct URL) unless the company has enabled it. See
 * docs/architecture/company-onboarding.md. Waits for the company to
 * load before deciding, so a hard refresh doesn't briefly bounce an
 * already-enabled company to 403 before its settings arrive. */
export function RequireErpEnabled({ children }: { children: ReactNode }) {
  const companyQuery = useCompanyQuery()
  const isErpEnabled = useIsErpEnabled()

  if (companyQuery.isPending) return null
  if (!isErpEnabled) {
    return <Navigate to="/403" replace />
  }

  return children
}

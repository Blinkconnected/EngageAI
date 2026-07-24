import { authHandlers } from './auth'
import { dashboardHandlers } from './dashboard'
import { companyHandlers } from './company'
import { departmentsHandlers } from './departments'
import { agentsHandlers } from './agents'

export const handlers = [
  ...authHandlers,
  ...dashboardHandlers,
  ...companyHandlers,
  ...departmentsHandlers,
  ...agentsHandlers,
]

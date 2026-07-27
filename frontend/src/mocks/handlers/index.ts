import { authHandlers } from './auth'
import { aiHandlers } from './ai'
import { dashboardHandlers } from './dashboard'
import { changelogHandlers } from './changelog'
import { companyHandlers } from './company'
import { departmentsHandlers } from './departments'
import { agentsHandlers } from './agents'
import { channelsHandlers } from './channels'
import { customersHandlers } from './customers'
import { queuesHandlers } from './queues'
import { rolesHandlers } from './roles'
import { slaHandlers } from './sla'
import { csatHandlers } from './csat'
import { conversationsHandlers } from './conversations'
import { notificationsHandlers } from './notifications'
import { erpHandlers } from './erp'
import { reportsHandlers } from './reports'
import { searchHandlers } from './search'

export const handlers = [
  ...authHandlers,
  ...aiHandlers,
  ...dashboardHandlers,
  ...changelogHandlers,
  ...companyHandlers,
  ...departmentsHandlers,
  ...agentsHandlers,
  ...channelsHandlers,
  ...customersHandlers,
  ...queuesHandlers,
  ...rolesHandlers,
  ...slaHandlers,
  ...csatHandlers,
  ...conversationsHandlers,
  ...notificationsHandlers,
  ...erpHandlers,
  ...reportsHandlers,
  ...searchHandlers,
]

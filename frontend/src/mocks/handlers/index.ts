import { authHandlers } from './auth'
import { dashboardHandlers } from './dashboard'
import { changelogHandlers } from './changelog'
import { companyHandlers } from './company'
import { departmentsHandlers } from './departments'
import { agentsHandlers } from './agents'
import { channelsHandlers } from './channels'
import { customersHandlers } from './customers'
import { queuesHandlers } from './queues'
import { conversationsHandlers } from './conversations'
import { notificationsHandlers } from './notifications'
import { erpHandlers } from './erp'
import { reportsHandlers } from './reports'

export const handlers = [
  ...authHandlers,
  ...dashboardHandlers,
  ...changelogHandlers,
  ...companyHandlers,
  ...departmentsHandlers,
  ...agentsHandlers,
  ...channelsHandlers,
  ...customersHandlers,
  ...queuesHandlers,
  ...conversationsHandlers,
  ...notificationsHandlers,
  ...erpHandlers,
  ...reportsHandlers,
]

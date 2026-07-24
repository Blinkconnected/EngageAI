import { Skeleton, Typography } from '@mui/material'
import { useCustomerQuery } from '../customers/api'

export function CustomerNameCell({ customerId }: { customerId: string }) {
  const customerQuery = useCustomerQuery(customerId)
  if (customerQuery.isPending) return <Skeleton width={120} />
  return <Typography variant="body2">{customerQuery.data?.full_name ?? customerId}</Typography>
}

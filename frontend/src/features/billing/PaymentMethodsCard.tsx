import {
  Card,
  CardContent,
  Chip,
  List,
  ListItem,
  ListItemText,
  Stack,
  Typography,
} from '@mui/material'
import { useTranslation } from 'react-i18next'
import type { PaymentMethod } from './types'

/**
 * How this customer can pay.
 *
 * Configuration-driven, never a hardcoded list: their country decides what is
 * offered and the deployment's provider registry decides what is configured,
 * and the API intersects the two. A method with no credentials behind it is
 * shown as unavailable rather than as a button that cannot work, and a
 * Jordanian customer is not offered PayPal merely because the product knows
 * the word.
 */
export function PaymentMethodsCard({ methods }: { methods: PaymentMethod[] }) {
  const { t } = useTranslation('billing')

  return (
    <Card variant="outlined" sx={{ height: '100%' }}>
      <CardContent>
        <Typography variant="subtitle1" component="h2" sx={{ fontWeight: 600, mb: 1 }}>
          {t('payment.title')}
        </Typography>
        {methods.length === 0 ? (
          <Typography variant="body2" color="text.secondary">
            {t('payment.empty')}
          </Typography>
        ) : (
          <List dense disablePadding>
            {methods.map((method) => (
              <ListItem key={method.code} disableGutters sx={{ alignItems: 'flex-start' }}>
                <ListItemText
                  primary={
                    <Stack
                      direction="row"
                      spacing={1}
                      sx={{ alignItems: 'center', flexWrap: 'wrap' }}
                    >
                      <Typography variant="body2">
                        {t(`payment.method.${method.code}`, { defaultValue: method.label })}
                      </Typography>
                      <Chip
                        size="small"
                        variant={method.available ? 'filled' : 'outlined'}
                        color={method.available ? 'success' : 'default'}
                        label={
                          method.available
                            ? t(method.self_serve ? 'payment.selfServe' : 'payment.byArrangement')
                            : t('payment.unavailable')
                        }
                      />
                    </Stack>
                  }
                  secondary={
                    method.unavailable_reason ??
                    t(method.self_serve ? 'payment.selfServeHint' : 'payment.arrangementHint')
                  }
                />
              </ListItem>
            ))}
          </List>
        )}
      </CardContent>
    </Card>
  )
}

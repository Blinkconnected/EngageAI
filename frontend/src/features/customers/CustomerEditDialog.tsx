import { useState } from 'react'
import { TextField } from '@mui/material'
import { FormDialog } from '../../shared/components/FormDialog'
import { extractErrorMessage } from '../../shared/api/errors'
import { useUpdateCustomerMutation } from './api'
import type { Customer } from './types'

export function CustomerEditDialog({
  customer,
  onClose,
}: {
  customer: Customer | null
  onClose: () => void
}) {
  if (!customer) return null
  return <CustomerEditDialogFields key={customer.id} customer={customer} onClose={onClose} />
}

function CustomerEditDialogFields({
  customer,
  onClose,
}: {
  customer: Customer
  onClose: () => void
}) {
  const [fullName, setFullName] = useState(customer.full_name)
  const [email, setEmail] = useState(customer.email ?? '')
  const [phone, setPhone] = useState(customer.phone ?? '')
  const [tags, setTags] = useState(customer.tags.join(', '))
  const updateMutation = useUpdateCustomerMutation(customer.id)

  function handleSubmit() {
    updateMutation.mutate(
      {
        full_name: fullName,
        email: email || null,
        phone: phone || null,
        tags: tags
          .split(',')
          .map((tag) => tag.trim())
          .filter(Boolean),
      },
      { onSuccess: onClose },
    )
  }

  return (
    <FormDialog
      open
      title="Edit customer"
      isSubmitting={updateMutation.isPending}
      error={updateMutation.error}
      errorMessage={updateMutation.error ? extractErrorMessage(updateMutation.error) : undefined}
      onSubmit={handleSubmit}
      onClose={onClose}
    >
      <TextField
        label="Full name"
        value={fullName}
        onChange={(event) => setFullName(event.target.value)}
        required
        fullWidth
        autoFocus
      />
      <TextField
        label="Email"
        type="email"
        value={email}
        onChange={(event) => setEmail(event.target.value)}
        fullWidth
      />
      <TextField
        label="Phone"
        value={phone}
        onChange={(event) => setPhone(event.target.value)}
        fullWidth
      />
      <TextField
        label="Tags"
        value={tags}
        onChange={(event) => setTags(event.target.value)}
        fullWidth
        helperText="Comma-separated"
      />
    </FormDialog>
  )
}

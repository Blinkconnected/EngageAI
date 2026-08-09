import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import Autocomplete from '@mui/material/Autocomplete'
import TextField from '@mui/material/TextField'

import { useCompaniesQuery } from '../platform/api'

/**
 * Choosing which company a finance question is about.
 *
 * Searches server-side rather than filtering a downloaded list: an
 * installation with a few thousand tenants would otherwise ship all of them
 * to the browser to answer one question about one of them.
 *
 * Note what this deliberately does *not* offer — no conversations, no
 * customers, no message counts. A billing operator picks a company to look at
 * its money. The tenant's own data stays out of reach of this console
 * entirely, which is the product promise, not a UI choice.
 */
export function CompanyPicker({
  value,
  onChange,
  label,
  size = 'small',
  sx,
}: {
  value: string | null
  onChange: (companyId: string | null) => void
  label?: string
  size?: 'small' | 'medium'
  sx?: object
}) {
  const { t } = useTranslation('billingOps')
  const [search, setSearch] = useState('')
  const query = useCompaniesQuery({ page: 1, page_size: 25, search: search || undefined })

  // Memoised because the `?? []` would otherwise be a new array identity on
  // every render, and the lookup below depends on it.
  const options = useMemo(() => query.data?.items ?? [], [query.data])
  // The selected company may not be on the current page of results once
  // somebody types a different search, and an Autocomplete whose value is
  // absent from its options clears itself. Keeping it pinned means a chosen
  // filter survives a search that no longer matches it.
  const selected = useMemo(
    () => options.find((company) => company.id === value) ?? null,
    [options, value],
  )

  return (
    <Autocomplete
      size={size}
      sx={{ minWidth: 240, ...sx }}
      options={options}
      loading={query.isLoading}
      value={selected}
      onChange={(_, next) => onChange(next?.id ?? null)}
      onInputChange={(_, text, reason) => reason === 'input' && setSearch(text)}
      getOptionLabel={(company) => company.name}
      isOptionEqualToValue={(company, other) => company.id === other.id}
      // The server already ordered and filtered; filtering again here would
      // hide results it deliberately returned.
      filterOptions={(items) => items}
      noOptionsText={t('filters.noCompanies')}
      renderInput={(params) => <TextField {...params} label={label ?? t('filters.company')} />}
    />
  )
}

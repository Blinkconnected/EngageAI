import { useMemo } from 'react'
import { Box, Checkbox, FormControlLabel, FormGroup, Stack, Typography } from '@mui/material'
import type { Permission } from './types'

// Overrides for resource-prefix acronyms that Title Case would otherwise
// mangle (e.g. "ai" -> "Ai").
const RESOURCE_LABEL_OVERRIDES: Record<string, string> = {
  ai: 'AI',
  erp: 'ERP',
}

function resourceLabel(resource: string): string {
  if (RESOURCE_LABEL_OVERRIDES[resource]) return RESOURCE_LABEL_OVERRIDES[resource]
  return resource
    .split('_')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ')
}

function groupByResource(permissions: Permission[]): [string, Permission[]][] {
  const groups = new Map<string, Permission[]>()
  for (const permission of permissions) {
    const resource = permission.code.split('.')[0]
    const items = groups.get(resource) ?? []
    items.push(permission)
    groups.set(resource, items)
  }
  return [...groups.entries()]
}

export function PermissionChecklist({
  permissions,
  selected,
  onChange,
  disabled = false,
}: {
  permissions: Permission[]
  selected: Set<string>
  onChange: (next: Set<string>) => void
  disabled?: boolean
}) {
  const groups = useMemo(() => groupByResource(permissions), [permissions])

  function toggle(code: string) {
    const next = new Set(selected)
    if (next.has(code)) {
      next.delete(code)
    } else {
      next.add(code)
    }
    onChange(next)
  }

  return (
    <Stack spacing={2}>
      {groups.map(([resource, items]) => (
        <Box key={resource}>
          <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
            {resourceLabel(resource)}
          </Typography>
          <FormGroup>
            {items.map((permission) => (
              <FormControlLabel
                key={permission.code}
                control={
                  <Checkbox
                    size="small"
                    checked={selected.has(permission.code)}
                    onChange={() => toggle(permission.code)}
                    disabled={disabled}
                  />
                }
                label={permission.description}
              />
            ))}
          </FormGroup>
        </Box>
      ))}
    </Stack>
  )
}

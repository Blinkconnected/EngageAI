export interface ChannelFieldsProps {
  credentials: Record<string, unknown>
  onChange: (credentials: Record<string, unknown>) => void
  /** Which channel is being configured. Only needed by components shared
   * across more than one type — Messenger and Instagram use the same
   * fields but need different wording about where the token comes from. */
  channelType?: string
}

export function fieldValue(credentials: Record<string, unknown>, key: string): string {
  const value = credentials[key]
  return value == null ? '' : String(value)
}

export function fieldBool(
  credentials: Record<string, unknown>,
  key: string,
  fallback: boolean,
): boolean {
  const value = credentials[key]
  return typeof value === 'boolean' ? value : fallback
}

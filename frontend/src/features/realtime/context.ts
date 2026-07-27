import { createContext, useContext } from 'react'

export interface RealtimeContextValue {
  sendTyping: (conversationId: string, isTyping: boolean) => void
  /** True while the customer on this conversation is currently typing —
   * only ever true for channels that support it (web_chat today; see
   * docs/architecture/web-chat.md's chat widget contract). */
  isCustomerTyping: (conversationId: string) => boolean
}

export const RealtimeContext = createContext<RealtimeContextValue>({
  sendTyping: () => {},
  isCustomerTyping: () => false,
})

export function useRealtime(): RealtimeContextValue {
  return useContext(RealtimeContext)
}

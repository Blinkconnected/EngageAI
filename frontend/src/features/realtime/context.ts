import { createContext, useContext } from 'react'

export interface RealtimeContextValue {
  sendTyping: (conversationId: string, isTyping: boolean) => void
}

export const RealtimeContext = createContext<RealtimeContextValue>({
  sendTyping: () => {},
})

export function useRealtime(): RealtimeContextValue {
  return useContext(RealtimeContext)
}

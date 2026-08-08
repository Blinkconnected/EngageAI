/** Matches the backend's `QuickReplyResponse`. */
export interface QuickReply {
  id: string
  /** What an agent types to reach it — `/refund`, `/hours`. Stored with
   * whatever leading character the author chose, so it is matched
   * loosely rather than assumed to start with a slash. */
  shortcut: string
  title: string
  body: string
  is_active: boolean
  created_at: string
  updated_at: string
}

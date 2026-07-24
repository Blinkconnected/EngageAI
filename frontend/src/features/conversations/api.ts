import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../../shared/api/client'
import type { Page, PageParams } from '../../shared/api/pagination'
import type {
  Attachment,
  Conversation,
  ConversationStatus,
  ConversationUpdateRequest,
  InternalNote,
  Message,
  SendMessageRequest,
} from './types'

const CONVERSATIONS_LIST_KEY = ['conversations', 'list']
const CONVERSATION_KEY = (id: string) => ['conversations', 'detail', id]
const MESSAGES_KEY = (conversationId: string) => ['conversations', conversationId, 'messages']
const NOTES_KEY = (conversationId: string) => ['conversations', conversationId, 'notes']

async function fetchConversations(
  params: PageParams & { status_filter?: ConversationStatus },
): Promise<Page<Conversation>> {
  const { data } = await apiClient.get<Page<Conversation>>('/conversations', { params })
  return data
}

async function fetchConversation(conversationId: string): Promise<Conversation> {
  const { data } = await apiClient.get<Conversation>(`/conversations/${conversationId}`)
  return data
}

async function updateConversation(
  conversationId: string,
  payload: ConversationUpdateRequest,
): Promise<Conversation> {
  const { data } = await apiClient.patch<Conversation>(`/conversations/${conversationId}`, payload)
  return data
}

async function fetchMessages(conversationId: string, params: PageParams): Promise<Page<Message>> {
  const { data } = await apiClient.get<Page<Message>>(`/conversations/${conversationId}/messages`, {
    params,
  })
  return data
}

async function sendMessage(conversationId: string, payload: SendMessageRequest): Promise<Message> {
  const { data } = await apiClient.post<Message>(
    `/conversations/${conversationId}/messages`,
    payload,
  )
  return data
}

async function uploadAttachment(conversationId: string, file: File): Promise<Attachment> {
  const formData = new FormData()
  formData.append('file', file)
  const { data } = await apiClient.post<Attachment>(
    `/conversations/${conversationId}/attachments`,
    formData,
    { headers: { 'Content-Type': 'multipart/form-data' } },
  )
  return data
}

async function fetchNotes(conversationId: string, params: PageParams): Promise<Page<InternalNote>> {
  const { data } = await apiClient.get<Page<InternalNote>>(
    `/conversations/${conversationId}/notes`,
    { params },
  )
  return data
}

async function createNote(conversationId: string, body: string): Promise<InternalNote> {
  const { data } = await apiClient.post<InternalNote>(`/conversations/${conversationId}/notes`, {
    body,
  })
  return data
}

export function useConversationsQuery(params: PageParams & { status_filter?: ConversationStatus }) {
  return useQuery({
    queryKey: [...CONVERSATIONS_LIST_KEY, params],
    queryFn: () => fetchConversations(params),
    placeholderData: (previousData) => previousData,
    refetchInterval: 30_000,
  })
}

export function useConversationQuery(conversationId: string | undefined) {
  return useQuery({
    queryKey: CONVERSATION_KEY(conversationId ?? ''),
    queryFn: () => fetchConversation(conversationId as string),
    enabled: Boolean(conversationId),
  })
}

export function useUpdateConversationMutation(conversationId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: ConversationUpdateRequest) => updateConversation(conversationId, payload),
    onSuccess: (data) => {
      queryClient.setQueryData(CONVERSATION_KEY(conversationId), data)
      void queryClient.invalidateQueries({ queryKey: CONVERSATIONS_LIST_KEY })
    },
  })
}

export function useMessagesQuery(conversationId: string | undefined, params: PageParams) {
  return useQuery({
    queryKey: [...MESSAGES_KEY(conversationId ?? ''), params],
    queryFn: () => fetchMessages(conversationId as string, params),
    enabled: Boolean(conversationId),
    placeholderData: (previousData) => previousData,
    refetchInterval: 15_000,
  })
}

export function useSendMessageMutation(conversationId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: SendMessageRequest) => sendMessage(conversationId, payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: MESSAGES_KEY(conversationId) })
      void queryClient.invalidateQueries({ queryKey: CONVERSATIONS_LIST_KEY })
    },
  })
}

export function useUploadAttachmentMutation(conversationId: string) {
  return useMutation({
    mutationFn: (file: File) => uploadAttachment(conversationId, file),
  })
}

export function useNotesQuery(conversationId: string | undefined, params: PageParams) {
  return useQuery({
    queryKey: [...NOTES_KEY(conversationId ?? ''), params],
    queryFn: () => fetchNotes(conversationId as string, params),
    enabled: Boolean(conversationId),
  })
}

export function useCreateNoteMutation(conversationId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: string) => createNote(conversationId, body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: NOTES_KEY(conversationId) }),
  })
}

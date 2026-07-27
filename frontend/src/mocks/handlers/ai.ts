import { http, HttpResponse } from 'msw'
import { API_BASE_URL } from '../apiBaseUrl'

export const MOCK_REPLY_SUGGESTION =
  "Thanks for reaching out — I've looked into this and here's what I found. Let me know if you have any other questions!"

export const MOCK_CONVERSATION_SUMMARY =
  'Customer reported an issue with their recent order and asked for a status update. Agent confirmed the order is on track and offered to follow up once it ships.'

export const aiHandlers = [
  http.post(`${API_BASE_URL}/ai/conversations/:conversationId/reply-suggestion`, () =>
    HttpResponse.json({ suggestion: MOCK_REPLY_SUGGESTION }),
  ),
  http.post(`${API_BASE_URL}/ai/conversations/:conversationId/summary`, () =>
    HttpResponse.json({ summary: MOCK_CONVERSATION_SUMMARY }),
  ),
]

import { isAxiosError } from 'axios'

interface ValidationErrorItem {
  loc: (string | number)[]
  msg: string
  type: string
}

interface ApiErrorBody {
  detail?: string | ValidationErrorItem[]
}

/**
 * Every backend error response is `{detail: string}` or, for request-body
 * validation failures, `{detail: ValidationErrorItem[]}` (see
 * docs/api/README.md's Errors section) — this is the one place that maps
 * either shape to a single display string.
 */
export function extractErrorMessage(error: unknown, fallback = 'Something went wrong.'): string {
  if (isAxiosError<ApiErrorBody>(error)) {
    const detail = error.response?.data?.detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail) && detail.length > 0) {
      return detail.map((item) => item.msg).join('; ')
    }
    if (error.response?.status === 429) return 'Too many requests — please wait and try again.'
    if (error.message) return error.message
  }
  return fallback
}

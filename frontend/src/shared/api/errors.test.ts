import { describe, expect, it } from 'vitest'
import { AxiosError, AxiosHeaders } from 'axios'
import { extractErrorMessage } from './errors'

function makeAxiosError(status: number, data: unknown): AxiosError {
  return new AxiosError('Request failed', String(status), undefined, undefined, {
    status,
    statusText: 'Error',
    data,
    headers: {},
    config: { headers: new AxiosHeaders() },
  })
}

describe('extractErrorMessage', () => {
  it('extracts a plain string detail', () => {
    expect(extractErrorMessage(makeAxiosError(400, { detail: 'Duplicate email' }))).toBe(
      'Duplicate email',
    )
  })

  it('joins validation error items into one message', () => {
    const error = makeAxiosError(422, {
      detail: [
        { loc: ['body', 'email'], msg: 'field required', type: 'value_error.missing' },
        { loc: ['body', 'password'], msg: 'too short', type: 'value_error' },
      ],
    })
    expect(extractErrorMessage(error)).toBe('field required; too short')
  })

  it('gives a dedicated message for rate limiting', () => {
    expect(extractErrorMessage(makeAxiosError(429, {}))).toMatch(/too many requests/i)
  })

  it('falls back to the provided default for non-axios errors', () => {
    expect(extractErrorMessage(new Error('boom'), 'fallback message')).toBe('fallback message')
    expect(extractErrorMessage('not an error', 'fallback message')).toBe('fallback message')
  })

  it('falls back to the axios error message when there is no response body', () => {
    const error = new AxiosError('Network Error')
    expect(extractErrorMessage(error, 'fallback message')).toBe('Network Error')
  })
})

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import type { Mock } from 'vitest'
import {
  ApiError, getDocuments, getMe, refreshSession, sendChatStream, setToken, setUnauthorizedHandler, SESSION_EXPIRED_MESSAGE,
} from './api'
import type { DoneEvent, Mode } from './api'
import { asResponse } from '../test/fixtures'

const encoder = new TextEncoder()

type FetchMock = Mock<typeof fetch>

/** Install a fetch double and return it, typed as a mock. */
function mockFetch(impl: (url: string, init?: RequestInit) => Promise<Response>): FetchMock {
  const fake = vi.fn((input: RequestInfo | URL, init?: RequestInit) => impl(String(input), init))
  globalThis.fetch = fake
  return fake
}

/** A fetch Response whose body arrives in the given pieces (strings or byte arrays). */
function streamResponse(pieces: (string | Uint8Array)[], { status = 200, json = {} }: { status?: number; json?: object } = {}): Response {
  let i = 0
  return asResponse({
    ok: status >= 200 && status < 300,
    status,
    json: async () => json,
    body: {
      getReader: () => ({
        read: async () => {
          if (i >= pieces.length) return { done: true, value: undefined }
          const piece = pieces[i++]
          return { done: false, value: typeof piece === 'string' ? encoder.encode(piece) : piece }
        },
      }),
    },
  })
}

const event = (data: object) => `data: ${JSON.stringify(data)}\n\n`

/** The headers a request was sent with, as a plain record. */
const headersOf = (fetch: FetchMock, call: number) => (fetch.mock.calls[call][1]?.headers ?? {}) as Record<string, string>

interface Calls {
  tokens: string[]
  done: DoneEvent[]
  errors: string[]
}

/** Run sendChatStream against the given response and record every callback. */
async function run(response: Response, options: { mode?: Mode } = {}): Promise<Calls> {
  mockFetch(async () => response)
  const calls: Calls = { tokens: [], done: [], errors: [] }
  await sendChatStream({
    question: 'How often?',
    sessionId: 'session_1',
    onToken: (t) => calls.tokens.push(t),
    onDone: (d) => calls.done.push(d),
    onError: (e) => calls.errors.push(e.message),
    ...options,
  })
  return calls
}

describe('sendChatStream', () => {
  beforeEach(() => {
    setToken('token-123')
  })

  afterEach(() => {
    setToken(null)
    setUnauthorizedHandler(null)
    vi.restoreAllMocks()
  })

  it('posts the question and mode with the token', async () => {
    await run(streamResponse([event({ type: 'done', sources: [], confidence: 0, turn_id: null })]), { mode: 'hybrid' })
    const fetch = globalThis.fetch as FetchMock
    const [url, init] = fetch.mock.calls[0]
    expect(url).toBe('/api/v1/chat/stream')
    expect(init?.method).toBe('POST')
    expect(headersOf(fetch, 0).Authorization).toBe('Bearer token-123')
    expect(JSON.parse(String(init?.body))).toEqual({
      question: 'How often?', session_id: 'session_1', mode: 'hybrid',
    })
  })

  it('reassembles events split across chunks, including a split character', async () => {
    const done = { type: 'done', sources: [{ source: 'café.txt', page: 1, snippet: '', score: 0.8 }], confidence: 0.8, turn_id: 4 }
    const bytes = encoder.encode(event({ type: 'token', content: 'Every ' }) + event({ type: 'token', content: '90 days, café' }) + event(done))
    const cafe = bytes.indexOf(0xc3)  // first byte of the two-byte é
    const pieces = [bytes.slice(0, 7), bytes.slice(7, 40), bytes.slice(40, cafe + 1), bytes.slice(cafe + 1)]

    const calls = await run(streamResponse(pieces))
    expect(calls.tokens).toEqual(['Every ', '90 days, café'])
    expect(calls.done).toEqual([done])
    expect(calls.errors).toEqual([])
  })

  it('handles several events in one chunk', async () => {
    const calls = await run(streamResponse([
      event({ type: 'token', content: 'a' }) + event({ type: 'token', content: 'b' }) + event({ type: 'done', sources: [] }),
    ]))
    expect(calls.tokens).toEqual(['a', 'b'])
    expect(calls.done).toHaveLength(1)
  })

  it('reads a final event that has no trailing newline', async () => {
    const calls = await run(streamResponse([
      event({ type: 'token', content: 'Hi' }),
      `data: ${JSON.stringify({ type: 'done', sources: [{ source: 'a.txt' }], confidence: 0.5 })}`,
    ]))
    expect(calls.tokens).toEqual(['Hi'])
    expect(calls.done).toEqual([{ type: 'done', sources: [{ source: 'a.txt' }], confidence: 0.5 }])
    expect(calls.errors).toEqual([])
  })

  it('reports an error when the stream ends without a done event', async () => {
    const calls = await run(streamResponse([event({ type: 'token', content: 'Half an ans' })]))
    expect(calls.tokens).toEqual(['Half an ans'])
    expect(calls.done).toEqual([])
    expect(calls.errors).toEqual(['The connection closed before the answer was complete. Please try again.'])
  })

  it('reports an error event and ignores anything after it', async () => {
    const calls = await run(streamResponse([
      event({ type: 'error', message: 'The answer could not be generated. Please try again.' }),
      event({ type: 'token', content: 'late' }),
      event({ type: 'done', sources: [] }),
    ]))
    expect(calls.errors).toEqual(['The answer could not be generated. Please try again.'])
    expect(calls.tokens).toEqual([])
    expect(calls.done).toEqual([])
  })

  it('gives an error event without a message a readable one', async () => {
    const calls = await run(streamResponse([event({ type: 'error' })]))
    expect(calls.errors).toEqual(['The answer could not be generated.'])
  })

  it('skips malformed and non-data lines', async () => {
    const calls = await run(streamResponse([
      ': keep-alive\n\n', 'data: {not json\n\n', 'event: ping\n', event({ type: 'token', content: 'ok' }), event({ type: 'done', sources: [] }),
    ]))
    expect(calls.tokens).toEqual(['ok'])
    expect(calls.done).toHaveLength(1)
    expect(calls.errors).toEqual([])
  })

  it('on 401 forgets the token, tells the app once and says the session expired', async () => {
    const onUnauthorized = vi.fn()
    setUnauthorizedHandler(onUnauthorized)

    const calls = await run(streamResponse([], { status: 401, json: { detail: 'Token has expired. Please log in again.' } }))
    expect(calls.errors).toEqual([SESSION_EXPIRED_MESSAGE])
    expect(onUnauthorized).toHaveBeenCalledTimes(1)

    // The token is gone: the next request carries no Authorization header and does not log out again
    const again = await run(streamResponse([], { status: 401 }))
    expect(headersOf(globalThis.fetch as FetchMock, 0).Authorization).toBeUndefined()
    expect(again.errors).toEqual([SESSION_EXPIRED_MESSAGE])
    expect(onUnauthorized).toHaveBeenCalledTimes(1)
  })

  it('shows the server detail for other HTTP errors', async () => {
    const calls = await run(streamResponse([], { status: 400, json: { detail: 'Question too long. Maximum 5000 characters.' } }))
    expect(calls.errors).toEqual(['Question too long. Maximum 5000 characters.'])
  })

  it('joins validation messages from a 422', async () => {
    const calls = await run(streamResponse([], { status: 422, json: { detail: [{ msg: 'bad session' }, { msg: 'bad mode' }] } }))
    expect(calls.errors).toEqual(['bad session; bad mode'])
  })

  it('reports a network failure', async () => {
    mockFetch(async () => { throw new TypeError('Failed to fetch') })
    const errors: string[] = []
    await sendChatStream({ question: 'q', onError: (e) => errors.push(e.message) })
    expect(errors).toEqual(['Failed to fetch'])
  })
})

/** A fetch that answers each call with the next response in the list, recording the calls. */
function answers(...responses: Response[]): FetchMock {
  return mockFetch(async () => responses.shift() ?? json(500, {}))
}

const json = (status: number, body: object, headers: Record<string, string> = {}) => asResponse({
  ok: status >= 200 && status < 300, status, json: async () => body, headers: new Headers(headers),
})

describe('renewing the access token', () => {
  afterEach(() => {
    setToken(null)
    setUnauthorizedHandler(null)
    vi.restoreAllMocks()
  })

  it('renews an expired token once and sends the request again with the new one', async () => {
    setToken('expired')
    const onUnauthorized = vi.fn()
    setUnauthorizedHandler(onUnauthorized)
    const fetch = answers(
      json(401, { detail: 'Token has expired. Please log in again.' }),
      json(200, { access_token: 'renewed', token_type: 'bearer', expires_in: 1800 }),
      json(200, { documents: ['a.txt'], count: 1 }),
    )
    expect(await getDocuments()).toEqual({ documents: ['a.txt'], count: 1 })
    expect(fetch.mock.calls.map(([url, init]) => [url, init?.method ?? 'GET'])).toEqual([
      ['/api/v1/documents', 'GET'], ['/api/v1/auth/refresh', 'POST'], ['/api/v1/documents', 'GET'],
    ])
    expect(headersOf(fetch, 0).Authorization).toBe('Bearer expired')
    expect(headersOf(fetch, 2).Authorization).toBe('Bearer renewed')
    expect(onUnauthorized).not.toHaveBeenCalled()
  })

  it('signs out when the refresh cookie is no longer valid', async () => {
    setToken('expired')
    const onUnauthorized = vi.fn()
    setUnauthorizedHandler(onUnauthorized)
    const fetch = answers(json(401, {}), json(401, { detail: 'Not signed in.' }))
    await expect(getDocuments()).rejects.toThrow(SESSION_EXPIRED_MESSAGE)
    expect(fetch).toHaveBeenCalledTimes(2)
    expect(onUnauthorized).toHaveBeenCalledTimes(1)
  })

  it('shares one renewal between requests that expire together', async () => {
    setToken('expired')
    let refreshes = 0
    mockFetch(async (url, init) => {
      if (url === '/api/v1/auth/refresh') {
        refreshes += 1
        return json(200, { access_token: 'renewed' })
      }
      const headers = (init?.headers ?? {}) as Record<string, string>
      return headers.Authorization === 'Bearer renewed' ? json(200, { documents: [] }) : json(401, {})
    })
    await Promise.all([getDocuments(), getDocuments(), getDocuments()])
    expect(refreshes).toBe(1)
  })

  it('restores a session from the refresh cookie after a reload, or says there is none', async () => {
    answers(json(200, { access_token: 'from-cookie', token_type: 'bearer', expires_in: 1800 }))
    expect((await refreshSession())?.access_token).toBe('from-cookie')
    const fetch = answers(json(200, { documents: [] }))
    await getDocuments()
    expect(headersOf(fetch, 0).Authorization).toBe('Bearer from-cookie')

    answers(json(401, { detail: 'Not signed in.' }))
    expect(await refreshSession()).toBeNull()
  })
})

describe('the request wrapper', () => {
  afterEach(() => {
    setToken(null)
    setUnauthorizedHandler(null)
    vi.restoreAllMocks()
  })

  it('asks the user to wait for as long as Retry-After says', async () => {
    setToken('t')
    answers(json(429, { error: 'Rate limit exceeded: 120 per 1 minute' }, { 'Retry-After': '42' }))
    await expect(getMe()).rejects.toThrow('Too many requests. Please wait 42 seconds and try again.')
  })

  it('asks the user to wait a moment when a 429 says nothing of how long', async () => {
    setToken('t')
    const onUnauthorized = vi.fn()
    setUnauthorizedHandler(onUnauthorized)
    answers(json(429, { error: 'Rate limit exceeded: 120 per 1 minute' }))
    const error = await getMe().catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).status).toBe(429)
    expect((error as ApiError).message).toBe('Too many requests. Please wait a moment and try again.')
    expect(onUnauthorized).not.toHaveBeenCalled()
  })

  it('shows a server error with its reference, and a bare failure by its status', async () => {
    setToken('t')
    answers(json(500, { detail: 'Something went wrong on the server. Please try again. Reference: 3f2a9c' }))
    await expect(getMe()).rejects.toThrow('Something went wrong on the server. Please try again. Reference: 3f2a9c')
    answers(json(502, {}))
    await expect(getMe()).rejects.toThrow('The request failed (error 502). Please try again.')
  })
})

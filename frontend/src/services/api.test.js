import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { sendChatStream, setToken, setUnauthorizedHandler, SESSION_EXPIRED_MESSAGE } from './api'

const encoder = new TextEncoder()

/** A fetch Response whose body arrives in the given pieces (strings or byte arrays). */
function streamResponse(pieces, { status = 200, json = {} } = {}) {
  let i = 0
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => json,
    body: {
      getReader: () => ({
        read: async () => (i < pieces.length
          ? { done: false, value: typeof pieces[i] === 'string' ? encoder.encode(pieces[i++]) : pieces[i++] }
          : { done: true, value: undefined }),
      }),
    },
  }
}

const event = (data) => `data: ${JSON.stringify(data)}\n\n`

/** Run sendChatStream against the given response and record every callback. */
async function run(response, options = {}) {
  globalThis.fetch = vi.fn(async () => response)
  const calls = { tokens: [], done: [], errors: [] }
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
    await run(streamResponse([event({ type: 'done', sources: [], confidence: 0 })]), { mode: 'hybrid' })
    const [url, init] = globalThis.fetch.mock.calls[0]
    expect(url).toBe('/api/v1/chat/stream')
    expect(init.method).toBe('POST')
    expect(init.headers.Authorization).toBe('Bearer token-123')
    expect(JSON.parse(init.body)).toEqual({
      question: 'How often?', session_id: 'session_1', mode: 'hybrid',
    })
  })

  it('reassembles events split across chunks, including a split character', async () => {
    const done = { type: 'done', sources: [{ source: 'café.txt', page: 1 }], confidence: 0.8 }
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
    expect(globalThis.fetch.mock.calls[0][1].headers.Authorization).toBeUndefined()
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
    globalThis.fetch = vi.fn(async () => { throw new TypeError('Failed to fetch') })
    const errors = []
    await sendChatStream({ question: 'q', onError: (e) => errors.push(e.message) })
    expect(errors).toEqual(['Failed to fetch'])
  })
})

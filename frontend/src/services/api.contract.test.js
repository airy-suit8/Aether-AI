/**
 * Contract: every call the API client makes matches a route in the backend's OpenAPI snapshot
 * (backend/tests/openapi_snapshot.json), and every field it sends is one that route accepts.
 * A renamed route or field on either side fails this test or the backend's snapshot test.
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import * as api from './api'
import snapshot from '../../../backend/tests/openapi_snapshot.json'

function resolve(schema) {
  if (schema?.$ref) return snapshot.components.schemas[schema.$ref.split('/').pop()]
  return schema
}

/** The schema's operation for a request. A path with a parameter, /documents/{document_id}, matches /documents/7. */
function operationFor(url, method) {
  if (snapshot.paths[url]?.[method]) return snapshot.paths[url][method]
  const template = Object.keys(snapshot.paths).find((path) =>
    path.includes('{') && snapshot.paths[path][method]
    && new RegExp(`^${path.replace(/\{[^}]+\}/g, '[^/]+')}$`).test(url))
  return template && snapshot.paths[template][method]
}

/** Call fn with a fetch that records the request and answers 200 with an empty stream. */
async function capture(fn) {
  let request
  globalThis.fetch = vi.fn(async (url, init = {}) => {
    request = { url, method: (init.method || 'GET').toLowerCase(), headers: init.headers || {}, body: init.body }
    return {
      ok: true, status: 200, json: async () => ({ access_token: 't', documents: [] }),
      body: { getReader: () => ({ read: async () => ({ done: true }) }) },
    }
  })
  await fn()
  return request
}

const CALLS = {
  register: () => api.register('someone', 'secret123', 'invite-code'),
  login: () => api.login('someone', 'secret123'),
  refreshSession: () => api.refreshSession(),
  logout: () => api.logout(),
  getMe: () => api.getMe(),
  getSessions: () => api.getSessions(),
  getSessionMessages: () => api.getSessionMessages('session_1'),
  uploadDocument: () => api.uploadDocument(new File(['hello'], 'a.txt', { type: 'text/plain' })),
  sendChat: () => api.sendChat({ question: 'q', sessionId: 's1', mode: 'hybrid' }),
  sendChatStream: () => api.sendChatStream({ question: 'q', sessionId: 's1' }),
  sendFeedback: () => api.sendFeedback(12, -1),
  getDocuments: () => api.getDocuments(),
  getDocumentsDetailed: () => api.getDocumentsDetailed(),
  getDocument: () => api.getDocument(7),
  deleteDocument: () => api.deleteDocument(7),
  deleteAllDocuments: () => api.deleteAllDocuments(),
  clearSession: () => api.clearSession('s1'),
  getHealth: () => api.getHealth(),
}

describe('API client contract with the backend schema', () => {
  afterEach(() => {
    api.setToken(null)
    vi.restoreAllMocks()
  })

  it('covers every request function the client exports', () => {
    const exported = Object.entries(api)
      .filter(([name, value]) => typeof value === 'function' && !/^set/.test(name))
      .map(([name]) => name)
    expect(exported.sort()).toEqual(Object.keys(CALLS).sort())
  })

  it.each(Object.keys(CALLS))('%s calls a route that exists, with fields it accepts', async (name) => {
    api.setToken('t')
    const request = await capture(CALLS[name])
    expect(request.url.startsWith('/api/v1/')).toBe(true)

    const operation = operationFor(request.url, request.method)
    expect(operation, `${request.method.toUpperCase()} ${request.url} is not in the backend schema`).toBeDefined()

    // A protected route gets the token; a public one does not need it
    const isProtected = (operation.security || []).length > 0
    if (isProtected) expect(request.headers.Authorization).toBe('Bearer t')

    const content = operation.requestBody?.content
    if (!content) {
      expect(request.body).toBeUndefined()
      return
    }
    let sent, schema
    if (typeof request.body === 'string') {
      sent = Object.keys(JSON.parse(request.body))
      schema = resolve(content['application/json']?.schema)
    } else if (request.body instanceof URLSearchParams) {
      sent = [...request.body.keys()]
      schema = resolve(content['application/x-www-form-urlencoded']?.schema)
    } else {
      sent = [...request.body.keys()]
      schema = resolve(content['multipart/form-data']?.schema)
    }
    expect(schema, `${name} sends a body type the route does not accept`).toBeDefined()
    for (const field of sent) expect(Object.keys(schema.properties)).toContain(field)
    for (const field of schema.required || []) expect(sent).toContain(field)
  })
})

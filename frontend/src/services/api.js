/**
 * api.js — Centralized API client for Aether AI Backend
 * All HTTP calls go through here for consistency.
 */

const BASE_URL = '/api/v1';  // Proxied via vite.config.js

let currentToken = null;
let onUnauthorized = null;

export const SESSION_EXPIRED_MESSAGE = 'Session expired. Please log in again.';

export function setToken(token) {
  currentToken = token;
}

/**
 * Register what to do when the server rejects our token (401): the app logs out.
 */
export function setUnauthorizedHandler(handler) {
  onUnauthorized = handler;
}

function getAuthHeaders(headers = {}) {
  if (currentToken) {
    return { ...headers, Authorization: `Bearer ${currentToken}` };
  }
  return headers;
}

function parseErrorMessage(errData, fallback) {
  if (!errData || !errData.detail) return fallback;
  if (typeof errData.detail === 'string') return errData.detail;
  if (Array.isArray(errData.detail)) {
    return errData.detail.map(d => d.msg || d.detail || JSON.stringify(d)).join('; ');
  }
  if (typeof errData.detail === 'object') return JSON.stringify(errData.detail);
  return fallback;
}

/**
 * Get a new access token with the refresh cookie the server set at sign-in (httpOnly, so this
 * code never sees it). Several requests that find the token expired share one renewal.
 * Resolves to true when a new token was set.
 */
let renewal = null;
function renewToken() {
  renewal ??= fetch(`${BASE_URL}/auth/refresh`, { method: 'POST' })
    .then(async (res) => {
      if (!res.ok) return false;
      setToken((await res.json()).access_token);
      return true;
    })
    .catch(() => false)
    .finally(() => { renewal = null; });
  return renewal;
}

/**
 * fetch with the access token. Access tokens last 30 minutes: on a 401 the token is renewed
 * once and the request sent again; if that fails too, checkResponse signs the user out.
 */
async function authFetch(url, init = {}) {
  const send = () => fetch(url, { ...init, headers: getAuthHeaders(init.headers) });
  const res = await send();
  if (res.status === 401 && currentToken && await renewToken()) return send();
  return res;
}

/**
 * Throw a readable error for a failed authenticated request.
 * A 401 means the token is no longer valid: forget it, tell the app once, and say so.
 */
async function checkResponse(res, fallback) {
  if (res.ok) return;
  if (res.status === 401 && currentToken) {
    currentToken = null;
    onUnauthorized?.();
    throw new Error(SESSION_EXPIRED_MESSAGE);
  }
  if (res.status === 401) throw new Error(SESSION_EXPIRED_MESSAGE);
  const err = await res.json().catch(() => null);
  throw new Error(parseErrorMessage(err, fallback));
}

/**
 * Authentication
 */
export async function register(username, password, inviteCode = '') {
  const res = await fetch(`${BASE_URL}/auth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    // The invite code is needed only when the server sets one
    body: JSON.stringify(inviteCode ? { username, password, invite_code: inviteCode } : { username, password }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => null);
    throw new Error(parseErrorMessage(err, 'Registration failed'));
  }
  return res.json();
}

export async function login(username, password) {
  const formData = new URLSearchParams();
  formData.append('username', username);
  formData.append('password', password);

  const res = await fetch(`${BASE_URL}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: formData,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => null);
    throw new Error(parseErrorMessage(err, 'Login failed'));
  }
  const data = await res.json();
  setToken(data.access_token);
  return data;
}

/**
 * Sign in again from the refresh cookie, as after a page reload. Returns the token data, or
 * null when there is no valid cookie (signed out, or a week without use).
 */
export async function refreshSession() {
  const res = await fetch(`${BASE_URL}/auth/refresh`, { method: 'POST' });
  if (!res.ok) return null;
  const data = await res.json();
  setToken(data.access_token);
  return data;
}

/**
 * Sign out on the server too: it removes the refresh cookie, so a reload stays signed out.
 */
export async function logout() {
  setToken(null);
  const res = await fetch(`${BASE_URL}/auth/logout`, { method: 'POST' });
  if (!res.ok) throw new Error('Sign-out failed');
  return res.json();
}

/**
 * Upload a document to the RAG pipeline
 */
export async function uploadDocument(file) {
  const formData = new FormData();
  formData.append('file', file);

  const res = await authFetch(`${BASE_URL}/upload`, {
    method: 'POST',
    body: formData,
  });

  await checkResponse(res, 'Upload failed');
  return res.json();
}

/**
 * Send a chat message (non-streaming).
 * mode is one of 'default', 'hybrid', 'agent' or 'langchain'.
 */
export async function sendChat({ question, sessionId = 'default', mode = 'default', signal }) {
  const res = await authFetch(`${BASE_URL}/chat`, {
    method: 'POST',
    signal,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      question,
      session_id: sessionId,
      mode,
    }),
  });

  await checkResponse(res, 'Chat failed');
  return res.json();
}

/**
 * Send a chat message with SSE streaming (mode as for sendChat)
 */
export async function sendChatStream({ question, sessionId = 'default', mode = 'default', signal, onToken, onDone, onError }) {
  try {
    const res = await authFetch(`${BASE_URL}/chat/stream`, {
      method: 'POST',
      signal,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        question,
        session_id: sessionId,
        mode,
      }),
    });

    await checkResponse(res, 'Stream failed');

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let finished = false;  // set by a 'done' or 'error' event

    const handleLine = (line) => {
      if (finished || !line.startsWith('data: ')) return;
      let data;
      try {
        data = JSON.parse(line.slice(6));
      } catch {
        return;  // Skip malformed SSE lines
      }
      if (data.type === 'token') {
        onToken?.(data.content);
      } else if (data.type === 'done') {
        finished = true;
        onDone?.(data);
      } else if (data.type === 'error') {
        finished = true;
        onError?.(new Error(data.message || 'The answer could not be generated.'));
      }
    };

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';
      lines.forEach(handleLine);
    }

    // The last event may arrive without a trailing newline
    buffer += decoder.decode();
    buffer.split('\n').forEach(handleLine);

    if (!finished) {
      onError?.(new Error('The connection closed before the answer was complete. Please try again.'));
    }
  } catch (err) {
    onError?.(err);
  }
}

/**
 * Get list of documents
 */
export async function getDocuments() {
  const res = await authFetch(`${BASE_URL}/documents`);
  await checkResponse(res, 'Failed to fetch documents');
  return res.json();
}

/**
 * Get detailed document info
 */
export async function getDocumentsDetailed() {
  const res = await authFetch(`${BASE_URL}/documents/detailed`);
  await checkResponse(res, 'Failed to fetch detailed documents');
  return res.json();
}

/**
 * Delete one document, by the id the detailed list gives it
 */
export async function deleteDocument(documentId) {
  const res = await authFetch(`${BASE_URL}/documents/${encodeURIComponent(documentId)}`, { method: 'DELETE' });
  await checkResponse(res, 'Failed to delete the document');
  return res.json();
}

/**
 * Delete all documents
 */
export async function deleteAllDocuments() {
  const res = await authFetch(`${BASE_URL}/documents`, { method: 'DELETE' });
  await checkResponse(res, 'Failed to delete documents');
  return res.json();
}

/**
 * Clear session conversation memory
 */
export async function clearSession(sessionId) {
  const res = await authFetch(`${BASE_URL}/session/clear`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question: '', session_id: sessionId }),
  });
  await checkResponse(res, 'Failed to clear session');
  return res.json();
}

/**
 * Health check
 */
export async function getHealth() {
  const res = await fetch(`${BASE_URL}/health`);
  if (!res.ok) throw new Error('Health check failed');
  return res.json();
}

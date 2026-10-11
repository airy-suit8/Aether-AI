/**
 * api.js — Centralized API client for Aether AI Backend
 * All HTTP calls go through here for consistency.
 */

const BASE_URL = '/api/v1';  // Proxied via vite.config.js

let currentToken = null;

export function setToken(token) {
  currentToken = token;
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
 * Authentication
 */
export async function register(username, password) {
  const res = await fetch(`${BASE_URL}/auth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
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
 * Upload a document to the RAG pipeline
 */
export async function uploadDocument(file) {
  const formData = new FormData();
  formData.append('file', file);

  const res = await fetch(`${BASE_URL}/upload`, {
    method: 'POST',
    headers: getAuthHeaders(),
    body: formData,
  });

  if (!res.ok) {
    const err = await res.json().catch(() => null);
    throw new Error(parseErrorMessage(err, 'Upload failed'));
  }
  return res.json();
}

/**
 * Send a chat message (non-streaming)
 */
export async function sendChat({ question, sessionId = 'default', useAgent = false, useLangchain = false, useHybrid = false }) {
  const res = await fetch(`${BASE_URL}/chat`, {
    method: 'POST',
    headers: getAuthHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({
      question,
      session_id: sessionId,
      use_agent: useAgent,
      use_langchain: useLangchain,
      use_hybrid: useHybrid,
    }),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => null);
    throw new Error(parseErrorMessage(err, 'Chat failed'));
  }
  return res.json();
}

/**
 * Send a chat message with SSE streaming
 */
export async function sendChatStream({ question, sessionId = 'default', useAgent = false, useLangchain = false, useHybrid = false, onToken, onDone, onError }) {
  try {
    const res = await fetch(`${BASE_URL}/chat/stream`, {
      method: 'POST',
      headers: getAuthHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({
        question,
        session_id: sessionId,
        use_agent: useAgent,
        use_langchain: useLangchain,
        use_hybrid: useHybrid,
      }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => null);
      throw new Error(parseErrorMessage(err, 'Stream failed'));
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try {
            const data = JSON.parse(line.slice(6));
            if (data.type === 'token') {
              onToken?.(data.content);
            } else if (data.type === 'done') {
              onDone?.(data);
            }
          } catch (e) {
            // Skip malformed SSE lines
          }
        }
      }
    }
  } catch (err) {
    onError?.(err);
  }
}

/**
 * Get list of documents
 */
export async function getDocuments() {
  const res = await fetch(`${BASE_URL}/documents`, { headers: getAuthHeaders() });
  if (!res.ok) throw new Error('Failed to fetch documents');
  return res.json();
}

/**
 * Get detailed document info
 */
export async function getDocumentsDetailed() {
  const res = await fetch(`${BASE_URL}/documents/detailed`, { headers: getAuthHeaders() });
  if (!res.ok) throw new Error('Failed to fetch detailed documents');
  return res.json();
}

/**
 * Delete all documents
 */
export async function deleteAllDocuments() {
  const res = await fetch(`${BASE_URL}/documents`, { method: 'DELETE', headers: getAuthHeaders() });
  if (!res.ok) throw new Error('Failed to delete documents');
  return res.json();
}

/**
 * Clear session conversation memory
 */
export async function clearSession(sessionId) {
  const res = await fetch(`${BASE_URL}/session/clear`, {
    method: 'POST',
    headers: getAuthHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ question: '', session_id: sessionId }),
  });
  if (!res.ok) throw new Error('Failed to clear session');
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

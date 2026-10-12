import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import App from './App'
import { AuthProvider } from './services/AuthContext'
import * as api from './services/api'

vi.mock('./services/api', async (importOriginal) => ({
  ...(await importOriginal()),
  refreshSession: vi.fn(),
  getMe: vi.fn(),
  getDocumentsDetailed: vi.fn(),
  getSessions: vi.fn(),
  getSessionMessages: vi.fn(),
}))

function renderApp() {
  return render(<AuthProvider><App /></AuthProvider>)
}

describe('App after a page reload', () => {
  beforeEach(() => {
    vi.mocked(api.getDocumentsDetailed).mockResolvedValue({ documents: [], count: 0 })
    vi.mocked(api.getSessions).mockResolvedValue({ sessions: [{ session_id: 'session_7' }] })
    vi.mocked(api.getSessionMessages).mockResolvedValue({ session_id: 'session_7', turns: [{
      turn_id: 1, question: 'What did we discuss?', answer: 'The turbine schedule.', sources: [],
      confidence: 0.7, mode: 'hybrid', tool_used: null, feedback: 0, created_at: '2026-10-12T10:00:00',
    }] })
  })

  it('keeps the user signed in and restores the conversation', async () => {
    vi.mocked(api.refreshSession).mockResolvedValue({ access_token: 'renewed', token_type: 'bearer', expires_in: 1800 })
    vi.mocked(api.getMe).mockResolvedValue({ username: 'Tirth', created_at: '2026-10-01T09:00:00' })
    renderApp()
    expect(await screen.findByText('What did we discuss?')).toBeTruthy()
    expect(screen.getByText('The turbine schedule.')).toBeTruthy()
    expect(screen.getByText('Tirth')).toBeTruthy()  // the real name, from /auth/me
  })

  it('shows the start page when there is no sign-in to restore', async () => {
    vi.mocked(api.refreshSession).mockResolvedValue(null)
    renderApp()
    expect(await screen.findByRole('heading', { level: 1 })).toBeTruthy()
    expect(api.getMe).not.toHaveBeenCalled()
    expect(screen.queryByText('What did we discuss?')).toBeNull()
  })
})

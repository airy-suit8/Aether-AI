import { describe, it, expect, vi, beforeEach } from 'vitest'
import { act, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, useLocation } from 'react-router'
import App from './App'
import { AuthProvider } from './services/AuthContext'
import * as api from './services/api'
import { asResponse, documentList, session, turn } from './test/fixtures'

vi.mock('./services/api', async (importOriginal) => ({
  ...(await importOriginal()),
  refreshSession: vi.fn(),
  getMe: vi.fn(),
  login: vi.fn(),
  logout: vi.fn(async () => ({ message: 'Signed out' })),
  getDocumentsDetailed: vi.fn(),
  getSessions: vi.fn(),
  getSessionMessages: vi.fn(),
  getSharedConversation: vi.fn(),
}))

function Where() {
  return <output data-testid="where">{useLocation().pathname}</output>
}

function renderApp(path = '/') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <App />
        <Where />
      </AuthProvider>
    </MemoryRouter>,
  )
}

const where = () => screen.getByTestId('where').textContent
const signedIn = () => {
  vi.mocked(api.refreshSession).mockResolvedValue({ access_token: 'renewed', token_type: 'bearer', expires_in: 1800 })
  vi.mocked(api.getMe).mockResolvedValue({ username: 'Tirth', created_at: '2026-10-01T09:00:00' })
}

describe('App after a page reload', () => {
  beforeEach(() => {
    vi.mocked(api.getMe).mockReset()
    vi.mocked(api.getDocumentsDetailed).mockResolvedValue(documentList([]))
    vi.mocked(api.getSessions).mockResolvedValue({ sessions: [session({ session_id: 'session_7' })] })
    vi.mocked(api.getSessionMessages).mockResolvedValue({ session_id: 'session_7', turns: [turn({
      turn_id: 1, question: 'What did we discuss?', answer: 'The turbine schedule.', sources: [],
      confidence: 0.7, mode: 'hybrid', tool_used: null, feedback: 0, created_at: '2026-10-12T10:00:00',
    })] })
  })

  it('keeps the user signed in and restores the conversation', async () => {
    signedIn()
    renderApp('/chat/session_7')
    expect(await screen.findByText('What did we discuss?')).toBeTruthy()
    expect(screen.getByText('The turbine schedule.')).toBeTruthy()
    expect(screen.getByText('Tirth')).toBeTruthy()  // the real name, from /auth/me
    expect(api.getSessionMessages).toHaveBeenCalledWith('session_7')
    expect(where()).toBe('/chat/session_7')
  })

  it('opens a shared conversation without a sign-in, and does not send the visitor to sign in', async () => {
    vi.mocked(api.refreshSession).mockResolvedValue(null)
    vi.mocked(api.getSharedConversation).mockResolvedValue({
      title: 'Blade inspections',
      turns: [{ question: 'How often?', answer: 'Every 90 days.', confidence: 0.8, mode: 'original', sources: [], tool_used: null, created_at: '2026-10-13T10:00:00' }],
    })
    renderApp('/shared/kQ3vX9pLm2Zr7TtYb5NwEa8HcJd4UfGs')
    expect(await screen.findByRole('heading', { level: 1, name: 'Blade inspections' })).toBeTruthy()
    expect(screen.getByText('Every 90 days.')).toBeTruthy()
    expect(where()).toBe('/shared/kQ3vX9pLm2Zr7TtYb5NwEa8HcJd4UfGs')
    expect(api.getMe).not.toHaveBeenCalled()
    expect(api.getSessions).not.toHaveBeenCalled()
  })

  it('shows the start page when there is no sign-in to restore', async () => {
    vi.mocked(api.refreshSession).mockResolvedValue(null)
    renderApp()
    expect(await screen.findByRole('heading', { level: 1 })).toBeTruthy()
    expect(api.getMe).not.toHaveBeenCalled()
    expect(screen.queryByText('What did we discuss?')).toBeNull()
  })

  it('/chat opens the most recent conversation', async () => {
    signedIn()
    renderApp('/chat')
    expect(await screen.findByText('What did we discuss?')).toBeTruthy()
    expect(where()).toBe('/chat/session_7')
  })

  it('keeps the start page at / for a signed-in user, who opens the workspace from it', async () => {
    signedIn()
    renderApp('/')
    const open = await screen.findAllByRole('button', { name: 'Open workspace' })
    await userEvent.setup().click(open[0])
    expect(await screen.findByText('What did we discuss?')).toBeTruthy()
    expect(where()).toBe('/chat/session_7')
  })
})

describe('App pages', () => {
  beforeEach(() => {
    vi.mocked(api.refreshSession).mockResolvedValue(null)
    vi.mocked(api.getDocumentsDetailed).mockResolvedValue(documentList([]))
    vi.mocked(api.getSessions).mockResolvedValue({ sessions: [] })
    vi.mocked(api.getSessionMessages).mockImplementation(async (id) => ({ session_id: id, turns: [] }))
  })

  it('/login is the start page with the sign-in sheet open; closing it goes back to /', async () => {
    renderApp('/login')
    expect(await screen.findByRole('dialog', { name: 'Welcome back' })).toBeTruthy()
    expect(screen.getByRole('heading', { level: 1 })).toBeTruthy()
    await userEvent.setup().keyboard('{Escape}')
    expect(where()).toBe('/')
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('sends a signed-out visit to a workspace page to sign in, and back there after', async () => {
    vi.mocked(api.login).mockResolvedValue({ access_token: 'fresh', token_type: 'bearer', expires_in: 1800 })
    renderApp('/settings')
    const sheet = await screen.findByRole('dialog', { name: 'Welcome back' })
    expect(where()).toBe('/login')

    const user = userEvent.setup()
    await user.type(within(sheet).getByLabelText('Username'), 'Tirth')
    await user.type(within(sheet).getByLabelText('Password'), 'a long password')
    await user.click(within(sheet).getByRole('button', { name: 'Sign in' }))
    expect(api.login).toHaveBeenCalledWith('Tirth', 'a long password')
    expect(await screen.findByRole('dialog', { name: 'Settings' })).toBeTruthy()
    expect(where()).toBe('/settings')
  })

  it('sends an unknown path to the start page', async () => {
    renderApp('/no/such/page')
    expect(await screen.findByRole('heading', { level: 1 })).toBeTruthy()
    expect(where()).toBe('/')
  })

  it('Sign out in the workspace goes to the start page, not to sign in', async () => {
    signedIn()
    renderApp('/chat/session_7')
    await userEvent.setup().click(await screen.findByRole('button', { name: 'Sign out' }))
    expect(where()).toBe('/')
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(screen.getByRole('heading', { level: 1 })).toBeTruthy()
    expect(api.logout).toHaveBeenCalled()
  })

  it('signs out to the start page, saying why, when the session cannot be renewed', async () => {
    signedIn()
    renderApp('/chat/session_7')
    expect(await screen.findByText('Tirth')).toBeTruthy()
    // Every request is refused from now on, the renewal of the token included
    globalThis.fetch = vi.fn(async () => asResponse({ ok: false, status: 401, json: async () => ({ detail: 'Not signed in.' }) }))
    await act(async () => {
      await expect(api.getDocuments()).rejects.toThrow(api.SESSION_EXPIRED_MESSAGE)
    })
    expect(where()).toBe('/')
    expect(screen.getByText(api.SESSION_EXPIRED_MESSAGE)).toBeTruthy()
    expect(screen.queryByText('Tirth')).toBeNull()
    expect(api.logout).toHaveBeenCalled()  // the refresh cookie is removed on the server too
  })
})

import { useState, useCallback, useEffect } from 'react'
import LandingPage from './components/landing/LandingPage'
import ChatLayout from './components/chat/ChatLayout'
import ToastContainer from './components/common/ToastContainer'
import type { Toast } from './components/common/ToastContainer'
import type { ToastType } from './components/chat/types'
import { useAuth } from './services/AuthContext'
import { getMe, refreshSession, setUnauthorizedHandler, SESSION_EXPIRED_MESSAGE } from './services/api'
import { PrismRoot } from './design/prism'
import type { Theme } from './design/prism'
import './design/app.css'

const THEME_KEY = 'aether_theme'

// The theme is a per-browser convenience, so it lives in localStorage; the page works without it.
function readTheme(): Theme {
  try {
    return localStorage.getItem(THEME_KEY) === 'dark' ? 'dark' : 'system'
  } catch {
    return 'system'
  }
}

/**
 * App.tsx — Root Application Controller
 * Manages view routing (landing ↔ chat), the theme and global toast notifications.
 */
export default function App() {
  const [view, setView] = useState<'landing' | 'chat'>('landing')
  const [toasts, setToasts] = useState<Toast[]>([])
  const [theme, setThemeState] = useState<Theme>(readTheme)
  const [restoring, setRestoring] = useState(true)
  const { isAuthenticated, login, logout } = useAuth()

  const setTheme = useCallback((next: Theme) => {
    setThemeState(next)
    try {
      localStorage.setItem(THEME_KEY, next)
    } catch {
      // Storage is blocked (private window): the choice lasts for this visit only
    }
  }, [])

  const addToast = useCallback((message: string, type: ToastType = 'info', duration = 4000) => {
    const id = Date.now() + Math.random()
    // Several requests can fail for the same reason at once: show each message only once
    setToasts(prev => prev.some(t => t.message === message) ? prev : [...prev, { id, message, type }])
    setTimeout(() => {
      setToasts(prev => prev.filter(t => t.id !== id))
    }, duration)
  }, [])

  const navigateToChat = useCallback(() => {
    setView('chat')
  }, [])

  const navigateToLanding = useCallback(() => {
    setView('landing')
  }, [])

  // A reload keeps the user signed in: the sign-in cookie gives a new token, /auth/me the name.
  // Until that is known nothing is shown, so the start page does not flash before the workspace.
  useEffect(() => {
    let cancelled = false
    const restore = async () => {
      try {
        const session = await refreshSession()
        if (!session || cancelled) return
        const me = await getMe()
        if (cancelled) return
        login(session.access_token, me.username)
        setView('chat')
      } catch {
        // The server is unreachable: show the start page, signed out
      } finally {
        if (!cancelled) setRestoring(false)
      }
    }
    restore()
    return () => { cancelled = true }
  }, [login])

  // The server rejected the token (expired, or the secret changed): log out and say why
  useEffect(() => {
    setUnauthorizedHandler(() => {
      logout()
      setView('landing')
      addToast(SESSION_EXPIRED_MESSAGE, 'error')
    })
    return () => setUnauthorizedHandler(null)
  }, [logout, addToast])

  return (
    <PrismRoot theme={theme}>
      {!restoring && (view === 'landing' || !isAuthenticated) && (
        <LandingPage onStartChat={navigateToChat} theme={theme} onTheme={setTheme} />
      )}
      {!restoring && view === 'chat' && isAuthenticated && (
        <ChatLayout
          onNavigateHome={navigateToLanding}
          addToast={addToast}
          theme={theme}
          onTheme={setTheme}
        />
      )}
      <ToastContainer toasts={toasts} />
    </PrismRoot>
  )
}

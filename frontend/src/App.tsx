import { useState, useCallback, useEffect } from 'react'
import type { ReactNode } from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router'
import LandingPage from './components/landing/LandingPage'
import ChatLayout from './components/chat/ChatLayout'
import SharedPage from './components/shared/SharedPage'
import ToastContainer from './components/common/ToastContainer'
import type { Toast } from './components/common/ToastContainer'
import type { ToastType } from './components/chat/types'
import { useAuth } from './services/AuthContext'
import { useSignOut } from './services/useSignOut'
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

/** A workspace page for signed-in users only; anyone else is sent to sign in, and back here after. */
function RequireAuth({ children }: { children: ReactNode }) {
  const { isAuthenticated } = useAuth()
  const location = useLocation()
  if (!isAuthenticated) return <Navigate to="/login" replace state={{ from: location.pathname }} />
  return children
}

/**
 * App.tsx — the root: the theme, toasts, the restored sign-in and the pages.
 *
 *   /                 the start page
 *   /login            the start page with the sign-in sheet open
 *   /chat             the most recent conversation, or a new one
 *   /chat/:threadId   one conversation; the thread id is its session_id
 *   /settings         the workspace with the settings sheet open
 *   /shared/:token    one conversation, read only, for anyone who has its link (no sign-in)
 *
 * The workspace pages share one ChatLayout, so opening settings keeps the conversation as it is.
 */
export default function App() {
  const [toasts, setToasts] = useState<Toast[]>([])
  const [theme, setThemeState] = useState<Theme>(readTheme)
  const [restoring, setRestoring] = useState(true)
  const { login } = useAuth()
  const signOut = useSignOut()

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

  // A reload keeps the user signed in: the sign-in cookie gives a new token, /auth/me the name.
  // Until that is known no page is shown, so a workspace page is not sent to sign in first.
  useEffect(() => {
    let cancelled = false
    const restore = async () => {
      try {
        const session = await refreshSession()
        if (!session || cancelled) return
        const me = await getMe()
        if (cancelled) return
        login(session.access_token, me.username)
      } catch {
        // The server is unreachable: show the page signed out
      } finally {
        if (!cancelled) setRestoring(false)
      }
    }
    restore()
    return () => { cancelled = true }
  }, [login])

  // The session could not be renewed (expired, or the secret changed): sign out to the start page and say why
  useEffect(() => {
    setUnauthorizedHandler(() => {
      signOut()
      addToast(SESSION_EXPIRED_MESSAGE, 'error')
    })
    return () => setUnauthorizedHandler(null)
  }, [signOut, addToast])

  const start = <LandingPage theme={theme} onTheme={setTheme} />
  const workspace = (
    <RequireAuth>
      <ChatLayout addToast={addToast} theme={theme} onTheme={setTheme} />
    </RequireAuth>
  )

  return (
    <PrismRoot theme={theme}>
      {!restoring && (
        <Routes>
          <Route element={start}>
            <Route index />
            <Route path="login" />
          </Route>
          <Route element={workspace}>
            <Route path="chat" />
            <Route path="chat/:threadId" />
            <Route path="settings" />
          </Route>
          <Route path="shared/:token" element={<SharedPage theme={theme} onTheme={setTheme} />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      )}
      <ToastContainer toasts={toasts} />
    </PrismRoot>
  )
}

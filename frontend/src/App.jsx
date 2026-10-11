import React, { useState, useCallback, useEffect } from 'react'
import LandingPage from './components/landing/LandingPage'
import ChatLayout from './components/chat/ChatLayout'
import ToastContainer from './components/common/ToastContainer'
import { useAuth } from './services/AuthContext'
import { setUnauthorizedHandler, SESSION_EXPIRED_MESSAGE } from './services/api'
import { PrismRoot } from './design/prism'
import './design/app.css'

const THEME_KEY = 'aether_theme'

// The theme is a per-browser convenience, so it lives in localStorage; the page works without it.
function readTheme() {
  try {
    return localStorage.getItem(THEME_KEY) === 'dark' ? 'dark' : 'system'
  } catch {
    return 'system'
  }
}

/**
 * App.jsx — Root Application Controller
 * Manages view routing (landing ↔ chat), the theme and global toast notifications.
 */
export default function App() {
  const [view, setView] = useState('landing')
  const [toasts, setToasts] = useState([])
  const [theme, setThemeState] = useState(readTheme)
  const { isAuthenticated, logout } = useAuth()

  const setTheme = useCallback((next) => {
    setThemeState(next)
    try {
      localStorage.setItem(THEME_KEY, next)
    } catch {
      // Storage is blocked (private window): the choice lasts for this visit only
    }
  }, [])

  const addToast = useCallback((message, type = 'info', duration = 4000) => {
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
      {(view === 'landing' || !isAuthenticated) && (
        <LandingPage onStartChat={navigateToChat} theme={theme} onTheme={setTheme} />
      )}
      {view === 'chat' && isAuthenticated && (
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

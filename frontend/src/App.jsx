import React, { useState, useCallback, useEffect } from 'react'
import LandingPage from './components/landing/LandingPage'
import ChatLayout from './components/chat/ChatLayout'
import ToastContainer from './components/common/ToastContainer'
import { useAuth } from './services/AuthContext'
import { setUnauthorizedHandler, SESSION_EXPIRED_MESSAGE } from './services/api'
import './App.css'

/**
 * App.jsx — Root Application Controller
 * Manages view routing (landing ↔ chat) and global toast notifications.
 */
export default function App() {
  const [view, setView] = useState('landing')
  const [toasts, setToasts] = useState([])
  const { isAuthenticated, logout } = useAuth()

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
    <>
      {(view === 'landing' || !isAuthenticated) && (
        <LandingPage onStartChat={navigateToChat} />
      )}
      {view === 'chat' && isAuthenticated && (
        <ChatLayout
          onNavigateHome={navigateToLanding}
          addToast={addToast}
        />
      )}
      <ToastContainer toasts={toasts} />
    </>
  )
}

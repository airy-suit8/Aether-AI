import React, { useState, useCallback } from 'react'
import LandingPage from './components/landing/LandingPage'
import ChatLayout from './components/chat/ChatLayout'
import ToastContainer from './components/common/ToastContainer'
import './App.css'

/**
 * App.jsx — Root Application Controller
 * Manages view routing (landing ↔ chat) and global toast notifications.
 */
export default function App() {
  const [view, setView] = useState('landing')
  const [toasts, setToasts] = useState([])

  const addToast = useCallback((message, type = 'info', duration = 4000) => {
    const id = Date.now() + Math.random()
    setToasts(prev => [...prev, { id, message, type }])
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

  return (
    <>
      {view === 'landing' && (
        <LandingPage onStartChat={navigateToChat} />
      )}
      {view === 'chat' && (
        <ChatLayout
          onNavigateHome={navigateToLanding}
          addToast={addToast}
        />
      )}
      <ToastContainer toasts={toasts} />
    </>
  )
}

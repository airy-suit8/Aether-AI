import React, { useState, useCallback, useRef, useEffect } from 'react'
import Sidebar from './Sidebar'
import ChatWindow from './ChatWindow'
import ChatComposer from './ChatComposer'
import SettingsModal from '../modals/SettingsModal'
import { sendChat, sendChatStream, uploadDocument, getDocuments, clearSession } from '../../services/api'
import { useAuth } from '../../services/AuthContext'
import { AmbientField, Lens } from '../../design/prism'

const THEMES = [
  { value: 'system', label: 'System' },
  { value: 'dark', label: 'Dark' },
]

const isWide = () => (typeof window.matchMedia === 'function' ? window.matchMedia('(min-width: 901px)').matches : true)

/**
 * ChatLayout — The main chat workspace with the library rail, the conversation and the composer.
 * Manages all chat state, the answer mode, sessions, and document lists.
 */
export default function ChatLayout({ onNavigateHome, addToast, theme = 'system', onTheme = () => {} }) {
  const { logout } = useAuth()

  // Messages
  const [messages, setMessages] = useState([])
  const [isLoading, setIsLoading] = useState(false)
  const [streamingText, setStreamingText] = useState('')
  const [streamingPhase, setStreamingPhase] = useState('')

  // One answer mode at a time, plus whether to stream
  const [mode, setMode] = useState('default') // default | hybrid | agent | langchain
  const [streamingMode, setStreamingMode] = useState(true)
  const agentMode = mode === 'agent'
  const langchainMode = mode === 'langchain'
  const hybridMode = mode === 'hybrid'

  // Session
  const [sessionId, setSessionId] = useState(() => `session_${Date.now()}`)

  // Documents
  const [documents, setDocuments] = useState([])

  // UI state
  const [sidebarOpen, setSidebarOpen] = useState(isWide)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [uploadProgress, setUploadProgress] = useState(null)

  const streamRef = useRef(null)
  const abortRef = useRef(null)

  const refreshDocuments = useCallback(async () => {
    try {
      const data = await getDocuments()
      setDocuments(data.documents || [])
    } catch (e) {
      console.error('Failed to load documents:', e)
    }
  }, [])

  // Load documents on mount
  useEffect(() => {
    refreshDocuments()
  }, [refreshDocuments])

  // A new message always scrolls into view; streamed text only follows if the reader is already at the bottom
  useEffect(() => {
    const el = streamRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [messages])

  useEffect(() => {
    const el = streamRef.current
    if (el && el.scrollHeight - el.scrollTop - el.clientHeight < 200) el.scrollTop = el.scrollHeight
  }, [streamingText])

  // ── Handle sending a message ──────────────────────────────────────────
  const handleSend = useCallback(async (question) => {
    if (!question.trim() || isLoading) return

    const userMessage = {
      id: Date.now(),
      role: 'user',
      content: question,
      timestamp: new Date().toISOString(),
    }
    setMessages(prev => [...prev, userMessage])
    setIsLoading(true)
    setStreamingText('')

    const controller = new AbortController()
    abortRef.current = controller
    const sentMode = agentMode ? 'agent' : langchainMode ? 'langchain' : hybridMode ? 'hybrid' : 'default'

    try {
      if (streamingMode && !agentMode) {
        // Streaming path
        setStreamingPhase('Searching your documents')
        let fullText = ''

        await sendChatStream({
          question,
          sessionId,
          useAgent: agentMode,
          useLangchain: langchainMode,
          useHybrid: hybridMode,
          signal: controller.signal,
          onToken: (token) => {
            setStreamingPhase('')
            fullText += token
            setStreamingText(fullText)
          },
          onDone: (data) => {
            const aiMessage = {
              id: Date.now() + 1,
              role: 'assistant',
              content: fullText,
              sources: data.sources || [],
              confidence: data.confidence || 0,
              toolUsed: data.tool_used || null,
              mode: sentMode,
              timestamp: new Date().toISOString(),
            }
            setMessages(prev => [...prev, aiMessage])
          },
          // Server error event, dropped connection, or missing 'done': show it, keep no partial answer
          onError: (err) => {
            if (err.name !== 'AbortError') addToast(err.message || 'Stream failed', 'error')
          },
        })
      } else {
        // Non-streaming path
        setStreamingPhase(agentMode ? 'The agent is working' : 'Reading your documents')
        const result = await sendChat({
          question,
          sessionId,
          useAgent: agentMode,
          useLangchain: langchainMode,
          useHybrid: hybridMode,
          signal: controller.signal,
        })

        const aiMessage = {
          id: Date.now() + 1,
          role: 'assistant',
          content: result.answer,
          sources: result.sources || [],
          confidence: result.confidence || 0,
          toolUsed: result.tool_used || null,
          mode: sentMode,
          timestamp: new Date().toISOString(),
        }
        setMessages(prev => [...prev, aiMessage])
      }
    } catch (err) {
      if (err.name !== 'AbortError') addToast(err.message || 'Failed to get response', 'error')
    } finally {
      // Always unlock the composer, whatever happened above
      abortRef.current = null
      setStreamingText('')
      setStreamingPhase('')
      setIsLoading(false)
    }
  }, [isLoading, sessionId, agentMode, langchainMode, streamingMode, hybridMode, addToast])

  // Stop reading the reply. The server may still finish and save its turn; that is fixed with the API work.
  const handleStop = useCallback(() => {
    abortRef.current?.abort()
  }, [])

  // ── Handle file upload ────────────────────────────────────────────────
  const handleUpload = useCallback(async (file) => {
    setUploadProgress({ filename: file.name, status: 'uploading' })
    try {
      const result = await uploadDocument(file)
      addToast(result.message, 'success')
      setUploadProgress(null)
      refreshDocuments()
    } catch (err) {
      addToast(err.message || 'Upload failed', 'error')
      setUploadProgress(null)
    }
  }, [addToast, refreshDocuments])

  // ── New thread ────────────────────────────────────────────────────────
  const handleNewThread = useCallback(async () => {
    abortRef.current?.abort()
    try {
      await clearSession(sessionId)
    } catch {
      // Silent — may fail if no session exists yet
    }
    const newId = `session_${Date.now()}`
    setSessionId(newId)
    setMessages([])
    setStreamingText('')
    addToast('New thread started', 'info')
  }, [sessionId, addToast])

  const handleLogout = useCallback(() => {
    abortRef.current?.abort()
    logout()
    onNavigateHome()
  }, [logout, onNavigateHome])

  const toggleSidebar = useCallback(() => setSidebarOpen(open => !open), [])
  const openSettings = useCallback(() => setSettingsOpen(true), [])
  const closeSettings = useCallback(() => setSettingsOpen(false), [])

  const fieldState = isLoading ? (streamingText ? 'streaming' : 'retrieving') : 'idle'

  return (
    <div className="x-shell" data-rail={sidebarOpen ? 'open' : 'closed'}>
      <AmbientField state={fieldState} />

      <Sidebar
        isOpen={sidebarOpen}
        onToggle={toggleSidebar}
        documents={documents}
        onUpload={handleUpload}
        uploadProgress={uploadProgress}
        onNewThread={handleNewThread}
        onOpenSettings={openSettings}
        onNavigateHome={onNavigateHome}
      />
      <button type="button" className="x-scrim" aria-label="Close the library" onClick={toggleSidebar} />

      <main className="x-main">
        <header className="x-top">
          <button
            type="button"
            className="p-icon-btn"
            aria-label={sidebarOpen ? 'Hide the library' : 'Show the library'}
            aria-expanded={sidebarOpen}
            onClick={toggleSidebar}
          >
            <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden="true">
              <rect x="2.5" y="3.5" width="15" height="13" rx="3" stroke="currentColor" strokeWidth="1.6" />
              <path d="M7.5 3.5v13" stroke="currentColor" strokeWidth="1.6" />
            </svg>
          </button>
          <span className="x-top__thread">
            <span className="p-eyebrow">Thread</span>
            <span className="p-mono">{sessionId.slice(-6)}</span>
          </span>
          <Lens label="Theme" options={THEMES} value={theme} onChange={onTheme} />
          {/* The rail has its own New thread; this one appears only while the rail is hidden */}
          {!sidebarOpen && (
            <button type="button" className="p-btn p-btn--tonal" onClick={handleNewThread}>New thread</button>
          )}
          <button type="button" className="p-btn" onClick={handleLogout}>Sign out</button>
        </header>

        <ChatWindow
          messages={messages}
          streamingText={streamingText}
          streamingPhase={streamingPhase}
          isLoading={isLoading}
          streamRef={streamRef}
          hasDocuments={documents.length > 0}
          onSuggest={handleSend}
        />

        <ChatComposer
          onSend={handleSend}
          onStop={handleStop}
          isLoading={isLoading}
          mode={mode}
          onMode={setMode}
          streaming={streamingMode}
          onStreaming={setStreamingMode}
          onUpload={handleUpload}
        />
      </main>

      {settingsOpen && (
        <SettingsModal
          onClose={closeSettings}
          addToast={addToast}
          onDocumentsChanged={refreshDocuments}
          onClearConversation={handleNewThread}
        />
      )}
    </div>
  )
}

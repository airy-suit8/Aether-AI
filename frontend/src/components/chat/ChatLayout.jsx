import React, { useState, useCallback, useRef, useEffect } from 'react'
import Sidebar from './Sidebar'
import ChatWindow from './ChatWindow'
import ChatComposer from './ChatComposer'
import SettingsModal from '../modals/SettingsModal'
import { sendChat, sendChatStream, uploadDocument, getDocuments, clearSession } from '../../services/api'
import { useAuth } from '../../services/AuthContext'
import DotPattern from '../reactbits/DotPattern'
import './ChatLayout.css'

/**
 * ChatLayout — The main chat workspace with sidebar, message area, and composer.
 * Manages all chat state, modes, sessions, and document lists.
 */
export default function ChatLayout({ onNavigateHome, addToast }) {
  const { logout } = useAuth()
  
  // Messages
  const [messages, setMessages] = useState([])
  const [isLoading, setIsLoading] = useState(false)
  const [streamingText, setStreamingText] = useState('')
  const [streamingPhase, setStreamingPhase] = useState('')

  // Modes
  const [agentMode, setAgentMode] = useState(false)
  const [langchainMode, setLangchainMode] = useState(false)
  const [streamingMode, setStreamingMode] = useState(true)
  const [hybridMode, setHybridMode] = useState(false)

  // Session
  const [sessionId, setSessionId] = useState(() => `session_${Date.now()}`)

  // Documents
  const [documents, setDocuments] = useState([])

  // UI state
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [uploadProgress, setUploadProgress] = useState(null)

  const chatEndRef = useRef(null)

  // Remove useEffect for localStorage

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

  // Auto-scroll
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, streamingText])

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

    const mode = agentMode ? 'agent' : langchainMode ? 'langchain' : 'original'

    try {
      if (streamingMode && !agentMode) {
        // Streaming path
        setStreamingPhase('Searching documents...')
        let fullText = ''

        await sendChatStream({
          question,
          sessionId,
          useAgent: agentMode,
          useLangchain: langchainMode,
          useHybrid: hybridMode,
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
              mode,
              timestamp: new Date().toISOString(),
            }
            setMessages(prev => [...prev, aiMessage])
            setStreamingText('')
            setStreamingPhase('')
            setIsLoading(false)
          },
          onError: (err) => {
            addToast(err.message || 'Stream failed', 'error')
            setStreamingText('')
            setStreamingPhase('')
            setIsLoading(false)
          },
        })
      } else {
        // Non-streaming path
        setStreamingPhase(agentMode ? 'Agent reasoning...' : 'Processing...')
        const result = await sendChat({
          question,
          sessionId,
          useAgent: agentMode,
          useLangchain: langchainMode,
          useHybrid: hybridMode,
        })

        const aiMessage = {
          id: Date.now() + 1,
          role: 'assistant',
          content: result.answer,
          sources: result.sources || [],
          confidence: result.confidence || 0,
          mode,
          timestamp: new Date().toISOString(),
        }
        setMessages(prev => [...prev, aiMessage])
        setStreamingPhase('')
        setIsLoading(false)
      }
    } catch (err) {
      addToast(err.message || 'Failed to get response', 'error')
      setStreamingPhase('')
      setIsLoading(false)
    }
  }, [isLoading, sessionId, agentMode, langchainMode, streamingMode, hybridMode, addToast])

  // ── Handle file upload ────────────────────────────────────────────────
  const handleUpload = useCallback(async (file) => {
    setUploadProgress({ filename: file.name, status: 'uploading' })
    try {
      const result = await uploadDocument(file)
      addToast(`✓ ${result.message}`, 'success')
      setUploadProgress(null)
      refreshDocuments()
    } catch (err) {
      addToast(err.message || 'Upload failed', 'error')
      setUploadProgress(null)
    }
  }, [addToast, refreshDocuments])

  // ── New thread ────────────────────────────────────────────────────────
  const handleNewThread = useCallback(async () => {
    try {
      await clearSession(sessionId)
    } catch (e) {
      // Silent — may fail if no session exists yet
    }
    const newId = `session_${Date.now()}`
    setSessionId(newId)
    setMessages([])
    setStreamingText('')
    addToast('New thread started', 'info')
  }, [sessionId, addToast])

  const handleLogout = useCallback(() => {
    logout()
    onNavigateHome()
  }, [logout, onNavigateHome])

  return (
    <div className="chat-layout">
      {/* Sidebar */}
      <Sidebar
        isOpen={sidebarOpen}
        onToggle={() => setSidebarOpen(!sidebarOpen)}
        documents={documents}
        onUpload={handleUpload}
        uploadProgress={uploadProgress}
        onNewThread={handleNewThread}
        onOpenSettings={() => setSettingsOpen(true)}
        sessionId={sessionId}
        onNavigateHome={onNavigateHome}
        agentMode={agentMode}
        langchainMode={langchainMode}
        streamingMode={streamingMode}
      />

      {/* Main workspace */}
      <main className={`chat-workspace ${sidebarOpen ? '' : 'sidebar-collapsed'}`}>
        <DotPattern width={20} height={20} cx={1} cy={1} cr={1} />
        {/* Header */}
        <header className="workspace-header glass-strong">
          <div className="header-left">
            <button className="btn btn-ghost btn-icon sidebar-toggle" onClick={() => setSidebarOpen(!sidebarOpen)}>
              ☰
            </button>
            <div className="session-info">
              <span className="session-label">Session</span>
              <span className="session-id">{sessionId.replace('session_', '').slice(0, 8)}</span>
            </div>
          </div>
          <div className="header-badges">
            {agentMode && <div className="badge badge-accent">🤖 Agent</div>}
            {langchainMode && <div className="badge badge-info">⛓️ LangChain</div>}
            {streamingMode && <div className="badge badge-success">⚡ Stream</div>}
            {hybridMode && <div className="badge badge-warning">🔀 Hybrid</div>}
          </div>
          <div className="header-right">
            <button className="btn btn-ghost btn-sm" onClick={handleNewThread}>
              ✦ New Thread
            </button>
            <button className="btn btn-ghost btn-sm" onClick={handleLogout} style={{ color: 'var(--accent-400)' }}>
              Log Out
            </button>
          </div>
        </header>

        {/* Chat area */}
        <ChatWindow
          messages={messages}
          streamingText={streamingText}
          streamingPhase={streamingPhase}
          isLoading={isLoading}
          chatEndRef={chatEndRef}
        />

        {/* Composer */}
        <ChatComposer
          onSend={handleSend}
          isLoading={isLoading}
          agentMode={agentMode}
          langchainMode={langchainMode}
          streamingMode={streamingMode}
          hybridMode={hybridMode}
          onToggleAgent={() => setAgentMode(!agentMode)}
          onToggleLangchain={() => setLangchainMode(!langchainMode)}
          onToggleStreaming={() => setStreamingMode(!streamingMode)}
          onToggleHybrid={() => setHybridMode(!hybridMode)}
          onUpload={handleUpload}
        />
      </main>

      {/* Settings modal */}
      {settingsOpen && (
        <SettingsModal
          onClose={() => setSettingsOpen(false)}
          addToast={addToast}
          onDocumentsChanged={refreshDocuments}
          onClearConversation={handleNewThread}
        />
      )}
    </div>
  )
}

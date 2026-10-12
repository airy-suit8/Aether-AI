import { useState, useCallback, useRef, useEffect } from 'react'
import { useMatch, useNavigate } from 'react-router'
import Sidebar from './Sidebar'
import ChatWindow from './ChatWindow'
import ChatComposer from './ChatComposer'
import SettingsModal from '../modals/SettingsModal'
import {
  sendChat, sendChatStream, uploadDocument, getDocument, getDocumentsDetailed, deleteDocument, clearSession,
  getSessions, getSessionMessages,
} from '../../services/api'
import type { DocumentRecord, Mode, Turn } from '../../services/api'
import { useSignOut } from '../../services/useSignOut'
import { AmbientField, Lens } from '../../design/prism'
import type { Theme } from '../../design/prism'
import type { AddToast, AnswerMessage, ChatMessage } from './types'

const THEMES: { value: Theme; label: string }[] = [
  { value: 'system', label: 'System' },
  { value: 'dark', label: 'Dark' },
]

// The server refuses larger files (AETHER_MAX_UPLOAD_BYTES); checked here first, so a big file
// is not sent only to be cut off
const MAX_UPLOAD_BYTES = 50 * 1024 * 1024

// An upload is read in the background; its status is checked this often, for at most ten minutes
const POLL_MS = 1000
const POLL_LIMIT = 600
const pause = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

// The database has always called the default mode "original"
const MODE_OF_STORED: Record<string, string> = { original: 'default' }

/** A saved turn as the two messages the conversation shows: the question and its answer. */
function turnToMessages(turn: Turn): ChatMessage[] {
  return [
    { id: `q${turn.turn_id}`, role: 'user', content: turn.question, timestamp: turn.created_at },
    {
      id: `a${turn.turn_id}`,
      role: 'assistant',
      content: turn.answer,
      sources: turn.sources || [],
      confidence: turn.confidence || 0,
      toolUsed: turn.tool_used || null,
      mode: MODE_OF_STORED[turn.mode] || turn.mode,
      turnId: turn.turn_id,
      feedback: turn.feedback === 1 || turn.feedback === -1 ? turn.feedback : 0,
      timestamp: turn.created_at,
    },
  ]
}

/** A new conversation's id. It is its URL (/chat/<id>) from the start; the server keeps it once it has a turn. */
const newThreadId = () => `session_${Date.now()}`

const isWide = () => (typeof window.matchMedia === 'function' ? window.matchMedia('(min-width: 901px)').matches : true)

interface ChatLayoutProps {
  addToast: AddToast
  theme?: Theme
  onTheme?: (theme: Theme) => void
}

/**
 * ChatLayout — The main chat workspace with the library rail, the conversation and the composer.
 * Manages all chat state, the answer mode, sessions, and document lists.
 *
 * The open conversation is in the URL (/chat/<thread id>), and so is the settings sheet
 * (/settings, over the conversation that was open). /chat opens the most recent conversation.
 */
export default function ChatLayout({ addToast, theme = 'system', onTheme = () => {} }: ChatLayoutProps) {
  const signOut = useSignOut()
  const navigate = useNavigate()
  const routeThread = useMatch('/chat/:threadId')?.params.threadId ?? null
  const settingsOpen = useMatch('/settings') !== null

  // Messages
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [streamingText, setStreamingText] = useState('')
  const [streamingPhase, setStreamingPhase] = useState('')

  // One answer mode at a time, plus whether to stream
  const [mode, setMode] = useState<Mode>('default')
  const [streamingMode, setStreamingMode] = useState(true)
  const agentMode = mode === 'agent'

  // The open conversation: the one in the URL, or under the settings sheet the one that was open
  const [sessionId, setSessionId] = useState<string | null>(routeThread)
  const threadId = routeThread ?? (settingsOpen ? sessionId : null)

  // Documents
  const [documents, setDocuments] = useState<DocumentRecord[]>([])

  // UI state
  const [sidebarOpen, setSidebarOpen] = useState(isWide)
  const [uploadProgress, setUploadProgress] = useState<{ filename: string; status: string } | null>(null)

  const streamRef = useRef<HTMLDivElement>(null)
  const abortRef = useRef<AbortController | null>(null)
  const mountedRef = useRef(true)
  const loadingRef = useRef<string | null>(null)  // the thread whose turns are being loaded

  useEffect(() => {
    mountedRef.current = true
    return () => { mountedRef.current = false }
  }, [])

  // Each document is { id, filename, ... }: the id is what removes it
  const refreshDocuments = useCallback(async () => {
    try {
      const data = await getDocumentsDetailed()
      setDocuments(data.documents || [])
    } catch (e) {
      console.error('Failed to load documents:', e)
    }
  }, [])

  // Load documents on mount
  useEffect(() => {
    refreshDocuments()
  }, [refreshDocuments])

  // /chat, or /settings opened directly: open the most recent conversation, or a new one
  useEffect(() => {
    if (threadId) return undefined
    let cancelled = false
    getSessions()
      .then(({ sessions }) => sessions[0]?.session_id ?? newThreadId())
      .catch(() => newThreadId())
      .then((id) => {
        if (cancelled) return
        if (settingsOpen) setSessionId(id)
        else navigate(`/chat/${id}`, { replace: true })
      })
    return () => { cancelled = true }
  }, [threadId, settingsOpen, navigate])

  // The conversation in the URL: show its turns, as they were saved
  useEffect(() => {
    if (!threadId) return undefined
    setSessionId(threadId)
    let cancelled = false
    loadingRef.current = threadId
    getSessionMessages(threadId)
      .then(({ turns }) => {
        // Not if the user has asked in it meanwhile: their question is already on screen
        if (cancelled || loadingRef.current !== threadId) return
        setMessages(turns.flatMap(turnToMessages))
      })
      .catch((e) => console.error('Failed to load the conversation:', e))
      .finally(() => { if (loadingRef.current === threadId) loadingRef.current = null })
    return () => { cancelled = true }
  }, [threadId])

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
  const handleSend = useCallback(async (question: string) => {
    if (!question.trim() || isLoading || !sessionId) return
    loadingRef.current = null

    const userMessage: ChatMessage = {
      id: `q${Date.now()}`,
      role: 'user',
      content: question,
      timestamp: new Date().toISOString(),
    }
    setMessages(prev => [...prev, userMessage])
    setIsLoading(true)
    setStreamingText('')

    const controller = new AbortController()
    abortRef.current = controller

    try {
      if (streamingMode && !agentMode) {
        // Streaming path
        setStreamingPhase('Searching your documents')
        let fullText = ''

        await sendChatStream({
          question,
          sessionId,
          mode,
          signal: controller.signal,
          onToken: (token) => {
            setStreamingPhase('')
            fullText += token
            setStreamingText(fullText)
          },
          onDone: (data) => {
            const aiMessage: AnswerMessage = {
              id: `a${Date.now()}`,
              role: 'assistant',
              content: fullText,
              sources: data.sources || [],
              confidence: data.confidence || 0,
              toolUsed: data.tool_used || null,
              turnId: data.turn_id ?? null,  // what feedback names it by
              feedback: 0,
              mode,
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
          mode,
          signal: controller.signal,
        })

        const aiMessage: AnswerMessage = {
          id: `a${Date.now()}`,
          role: 'assistant',
          content: result.answer,
          sources: result.sources || [],
          confidence: result.confidence || 0,
          toolUsed: result.tool_used || null,
          turnId: result.turn_id ?? null,
          feedback: 0,
          mode,
          timestamp: new Date().toISOString(),
        }
        setMessages(prev => [...prev, aiMessage])
      }
    } catch (err) {
      if (err instanceof Error && err.name !== 'AbortError') addToast(err.message || 'Failed to get response', 'error')
    } finally {
      // Always unlock the composer, whatever happened above
      abortRef.current = null
      setStreamingText('')
      setStreamingPhase('')
      setIsLoading(false)
    }
  }, [isLoading, sessionId, mode, agentMode, streamingMode, addToast])

  // Stop reading the reply. The server may still finish and save its turn; that is fixed with the API work.
  const handleStop = useCallback(() => {
    abortRef.current?.abort()
  }, [])

  // ── Handle file upload ────────────────────────────────────────────────
  const handleUpload = useCallback(async (file: File) => {
    if (file.size > MAX_UPLOAD_BYTES) {
      addToast(`${file.name} is larger than 50 MB, the most one file may be.`, 'error')
      return
    }
    setUploadProgress({ filename: file.name, status: 'uploading' })
    try {
      const accepted = await uploadDocument(file)
      refreshDocuments()  // it shows in the library as being read
      let doc = await getDocument(accepted.document_id)
      for (let tries = 0; doc.status === 'processing' && tries < POLL_LIMIT && mountedRef.current; tries++) {
        await pause(POLL_MS)
        doc = await getDocument(accepted.document_id)
      }
      if (!mountedRef.current) return
      if (doc.status === 'ready') {
        const count = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`
        const replaced = accepted.replaces ? ' It replaced the earlier file of that name.' : ''
        addToast(`Added ${doc.filename}: ${count(doc.chunks, 'passage')} from ${count(doc.pages, 'page')}.${replaced}`, 'success')
      } else if (doc.status === 'failed') {
        addToast(doc.error || `${doc.filename} could not be read.`, 'error')
        // Nothing of it was kept; its record leaves the library too
        await deleteDocument(doc.id).catch(() => {})
      } else {
        addToast(`Still reading ${doc.filename}. It will appear in your library when it is ready.`, 'info')
      }
    } catch (err) {
      addToast(err instanceof Error ? err.message : 'Upload failed', 'error')
    } finally {
      if (mountedRef.current) {
        setUploadProgress(null)
        refreshDocuments()
      }
    }
  }, [addToast, refreshDocuments])

  // ── Remove one document ───────────────────────────────────────────────
  const handleRemoveDocument = useCallback(async (doc: DocumentRecord) => {
    try {
      await deleteDocument(doc.id)
      addToast(`Removed ${doc.filename}`, 'info')
    } catch (err) {
      addToast(err instanceof Error ? err.message : 'Could not remove the document', 'error')
    }
    await refreshDocuments()
  }, [addToast, refreshDocuments])

  // ── New thread: a fresh session; the old one stays on the server ─────
  const startThread = useCallback(() => {
    abortRef.current?.abort()
    setMessages([])
    setStreamingText('')
    navigate(`/chat/${newThreadId()}`)
  }, [navigate])

  const handleNewThread = useCallback(() => {
    startThread()
    addToast('New thread started', 'info')
  }, [startThread, addToast])

  // ── Settings: delete the current conversation from the server, then start a new thread ──
  const handleClearConversation = useCallback(async () => {
    if (!sessionId) return
    try {
      await clearSession(sessionId)
      startThread()
      addToast('Conversation deleted', 'info')
    } catch (err) {
      addToast(err instanceof Error ? err.message : 'Could not delete the conversation', 'error')
    }
  }, [sessionId, startThread, addToast])

  const handleLogout = useCallback(() => {
    abortRef.current?.abort()
    signOut()
  }, [signOut])

  const goHome = useCallback(() => navigate('/'), [navigate])
  const toggleSidebar = useCallback(() => setSidebarOpen(open => !open), [])
  const openSettings = useCallback(() => navigate('/settings'), [navigate])
  const closeSettings = useCallback(() => navigate(sessionId ? `/chat/${sessionId}` : '/chat'), [navigate, sessionId])

  const fieldState = isLoading ? (streamingText ? 'streaming' : 'retrieving') : 'idle'

  return (
    <div className="x-shell" data-rail={sidebarOpen ? 'open' : 'closed'}>
      <AmbientField state={fieldState} />

      <Sidebar
        isOpen={sidebarOpen}
        onToggle={toggleSidebar}
        documents={documents}
        onRemoveDocument={handleRemoveDocument}
        onUpload={handleUpload}
        uploadProgress={uploadProgress}
        onNewThread={handleNewThread}
        onOpenSettings={openSettings}
        onNavigateHome={goHome}
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
            <span className="p-mono">{sessionId?.slice(-6)}</span>
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
          onClearConversation={handleClearConversation}
        />
      )}
    </div>
  )
}

import { useState, useCallback, useRef, useEffect } from 'react'
import { useMatch, useNavigate } from 'react-router'
import Sidebar from './Sidebar'
import ChatWindow from './ChatWindow'
import ChatComposer from './ChatComposer'
import SettingsModal from '../modals/SettingsModal'
import {
  sendChat, sendChatStream, sendFeedback, uploadDocument, getDocument, getDocumentsDetailed, deleteDocument, clearSession,
  getSessions, getSessionMessages,
} from '../../services/api'
import type { DocumentRecord, FeedbackValue, Mode, SessionSummary, Turn } from '../../services/api'
import { useSignOut } from '../../services/useSignOut'
import { AmbientField, Lens } from '../../design/prism'
import type { Theme } from '../../design/prism'
import type { AddToast, AnswerMessage, ChatMessage, Failure } from './types'

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

const STOPPED = 'Your question is back in the box below. Nothing was saved.'

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

  // The open conversation: the one in the URL, or under the settings sheet the one that was open
  const [sessionId, setSessionId] = useState<string | null>(routeThread)
  const threadId = routeThread ?? (settingsOpen ? sessionId : null)

  // Messages, and the reply being written (shown only in the thread it was asked in)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [pending, setPending] = useState<{ run: number; threadId: string; question: string } | null>(null)
  const [streamingText, setStreamingText] = useState('')
  const [streamingPhase, setStreamingPhase] = useState('')
  const [failure, setFailure] = useState<Failure | null>(null)
  const [composerText, setComposerText] = useState<{ text: string } | null>(null)
  const isLoading = pending !== null && pending.threadId === sessionId

  // One answer mode at a time, plus whether to stream
  const [mode, setMode] = useState<Mode>('default')
  const [streamingMode, setStreamingMode] = useState(true)

  // Documents, and the conversations listed in the rail
  const [documents, setDocuments] = useState<DocumentRecord[]>([])
  const [threads, setThreads] = useState<SessionSummary[]>([])
  const [threadLoading, setThreadLoading] = useState(false)

  // UI state
  const [sidebarOpen, setSidebarOpen] = useState(isWide)
  const [uploadProgress, setUploadProgress] = useState<{ filename: string; status: string } | null>(null)

  const streamRef = useRef<HTMLDivElement>(null)
  const abortRef = useRef<AbortController | null>(null)
  const runRef = useRef(0)                          // the latest reply asked for
  const threadRef = useRef<string | null>(sessionId) // the thread open now, for replies still on their way
  threadRef.current = sessionId
  const mountedRef = useRef(true)
  const loadingRef = useRef<string | null>(null)  // the thread whose turns are being loaded
  const atBottomRef = useRef(true)                  // the reader is at the foot of the conversation

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      abortRef.current?.abort()  // leaving the workspace: nothing is left to show the reply
    }
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

  // The user's conversations, most recently used first (title and date)
  const refreshThreads = useCallback(async () => {
    try {
      setThreads((await getSessions()).sessions)
    } catch (e) {
      console.error('Failed to load the conversations:', e)
    }
  }, [])

  // Load documents and conversations on mount
  useEffect(() => {
    refreshDocuments()
    refreshThreads()
  }, [refreshDocuments, refreshThreads])

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
    // A reply still on its way belongs to the thread that was open: it goes on, and the server
    // saves it there, but nothing of it is shown here, now or if the user comes back before it ends
    runRef.current += 1
    abortRef.current = null
    setPending(null)
    setStreamingText('')
    setStreamingPhase('')
    setMessages([])
    setThreadLoading(true)
    atBottomRef.current = true  // a conversation opens at its latest turn
    let cancelled = false
    loadingRef.current = threadId
    getSessionMessages(threadId)
      .then(({ turns }) => {
        // Not if the user has asked in it meanwhile: their question is already on screen
        if (cancelled || loadingRef.current !== threadId) return
        setMessages(turns.flatMap(turnToMessages))
      })
      .catch((e) => console.error('Failed to load the conversation:', e))
      .finally(() => {
        if (loadingRef.current === threadId) loadingRef.current = null
        if (!cancelled) setThreadLoading(false)
      })
    return () => { cancelled = true }
  }, [threadId])

  // The conversation follows new text only while the reader is at the bottom: their own question
  // always scrolls into view, but an answer arriving while they read further up does not move them
  const followScroll = useCallback(() => {
    const el = streamRef.current
    if (el) atBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 200
  }, [])

  useEffect(() => {
    const el = streamRef.current
    if (el && (messages[messages.length - 1]?.role === 'user' || atBottomRef.current)) el.scrollTop = el.scrollHeight
  }, [messages])

  useEffect(() => {
    const el = streamRef.current
    if (el && atBottomRef.current) el.scrollTop = el.scrollHeight
  }, [streamingText])

  // ── Asking: one reply at a time, tied to the thread it was asked in ──────
  //
  // A reply is a run. Its callbacks write to the screen only while it is the latest run and its
  // thread is still open, so a reply that finishes after its thread was left is discarded here
  // (the server has saved it to its own thread). Stop closes the stream, which is the only
  // signal the server gets: it then saves no turn. A reply that fails or is stopped takes its
  // question out of the conversation and puts it back in the composer, with a Retry action.
  const askedIn = useCallback((run: number, thread: string) => runRef.current === run && threadRef.current === thread, [])

  const handleSend = useCallback(async (question: string) => {
    if (!question.trim() || !sessionId || pending?.threadId === sessionId) return
    loadingRef.current = null  // the user's question wins over a load still on its way
    const thread = sessionId
    const run = ++runRef.current
    const questionId = `q${run}-${Date.now()}`

    setFailure(null)
    setMessages(prev => [...prev, { id: questionId, role: 'user', content: question, timestamp: new Date().toISOString() }])
    setPending({ run, threadId: thread, question })
    setStreamingText('')
    setStreamingPhase(mode === 'agent' ? 'The agent is working' : 'Searching your documents')

    const controller = new AbortController()
    abortRef.current = controller

    const answered = (answer: Omit<AnswerMessage, 'id' | 'role' | 'feedback' | 'mode' | 'timestamp'>) => {
      refreshThreads()  // a new turn, here or in a thread that was left: the list's order changes
      if (!askedIn(run, thread)) return
      setMessages(prev => [...prev, {
        ...answer, id: `a${run}-${Date.now()}`, role: 'assistant', feedback: 0, mode, timestamp: new Date().toISOString(),
      }])
    }
    const failed = (err: Error) => {
      if (!askedIn(run, thread)) return
      const stopped = err.name === 'AbortError'
      setMessages(prev => prev.filter(m => m.id !== questionId))
      setFailure({ threadId: thread, question, stopped, message: stopped ? STOPPED : err.message || 'The answer could not be generated.' })
      setComposerText({ text: question })
    }

    try {
      if (streamingMode) {
        let fullText = ''
        await sendChatStream({
          question,
          sessionId: thread,
          mode,
          signal: controller.signal,
          onToken: (token) => {
            fullText += token
            if (!askedIn(run, thread)) return
            setStreamingPhase('')
            setStreamingText(fullText)
          },
          onDone: (data) => answered({
            content: fullText,
            sources: data.sources || [],
            confidence: data.confidence || 0,
            toolUsed: data.tool_used || null,
            turnId: data.turn_id ?? null,  // what feedback names it by
          }),
          // A server error event, a dropped connection, a missing done event, or Stop
          onError: failed,
        })
      } else {
        const result = await sendChat({ question, sessionId: thread, mode, signal: controller.signal })
        answered({
          content: result.answer,
          sources: result.sources || [],
          confidence: result.confidence || 0,
          toolUsed: result.tool_used || null,
          turnId: result.turn_id ?? null,
        })
      }
    } catch (err) {
      failed(err instanceof Error ? err : new Error(String(err)))
    } finally {
      // Unlock the composer, whatever happened above, unless a later question has taken over
      if (runRef.current === run) {
        abortRef.current = null
        setPending(null)
        setStreamingText('')
        setStreamingPhase('')
      }
    }
  }, [sessionId, pending, mode, streamingMode, askedIn, refreshThreads])

  // Stop the reply: close its stream. Only a streamed reply can be stopped (see ChatComposer).
  const handleStop = useCallback(() => {
    abortRef.current?.abort()
  }, [])

  const handleRetry = useCallback(() => {
    if (!failure) return
    setComposerText({ text: '' })
    handleSend(failure.question)
  }, [failure, handleSend])

  // ── Rate an answer: up, down, or 0 to take it back ────────────────────
  // Shown at once; put back as it was if the server does not record it
  const handleRate = useCallback(async (message: AnswerMessage, value: FeedbackValue) => {
    if (message.turnId == null) return
    const setFeedback = (feedback: FeedbackValue) =>
      setMessages(prev => prev.map(m => (m.id === message.id && m.role === 'assistant' ? { ...m, feedback } : m)))
    setFeedback(value)
    try {
      await sendFeedback(message.turnId, value)
    } catch (err) {
      setFeedback(message.feedback)
      addToast(err instanceof Error ? err.message : 'Could not record the rating', 'error')
    }
  }, [addToast])

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
  // A reply still on its way goes on, and is saved to the thread it was asked in.
  const startThread = useCallback(() => {
    setMessages([])
    navigate(`/chat/${newThreadId()}`)
  }, [navigate])

  // On a narrow screen the rail is a drawer over the conversation: close it once a thread is chosen
  const chooseThread = useCallback(() => {
    if (!isWide()) setSidebarOpen(false)
  }, [])

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
      refreshThreads()
      addToast('Conversation deleted', 'info')
    } catch (err) {
      addToast(err instanceof Error ? err.message : 'Could not delete the conversation', 'error')
    }
  }, [sessionId, startThread, refreshThreads, addToast])

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
        threads={threads}
        currentThread={sessionId}
        onChooseThread={chooseThread}
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
          streamingText={isLoading ? streamingText : ''}
          streamingPhase={isLoading ? streamingPhase : ''}
          isLoading={isLoading}
          threadLoading={threadLoading}
          streamRef={streamRef}
          onScroll={followScroll}
          hasDocuments={documents.length > 0}
          onSuggest={handleSend}
          onRate={handleRate}
        />

        <ChatComposer
          onSend={handleSend}
          onStop={handleStop}
          onRetry={handleRetry}
          failure={failure?.threadId === sessionId ? failure : null}
          restore={composerText}
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

import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router'
import MessageBubble from '../chat/MessageBubble'
import type { ChatMessage } from '../chat/types'
import { ApiError, getSharedConversation } from '../../services/api'
import type { SharedConversation, SharedTurn } from '../../services/api'
import { AmbientField, Lens, PrismMark } from '../../design/prism'
import type { Theme } from '../../design/prism'

const THEMES: { value: Theme; label: string }[] = [
  { value: 'system', label: 'System' },
  { value: 'dark', label: 'Dark' },
]

// The database has always called the default mode "original"
const MODE_OF_STORED: Record<string, string> = { original: 'default' }

/** A shared turn as the two messages a conversation shows. It has no turn id: it cannot be rated here. */
function toMessages(turn: SharedTurn, index: number): ChatMessage[] {
  return [
    { id: `q${index}`, role: 'user', content: turn.question, timestamp: turn.created_at },
    {
      id: `a${index}`,
      role: 'assistant',
      content: turn.answer,
      sources: turn.sources || [],
      confidence: turn.confidence || 0,
      toolUsed: turn.tool_used || null,
      mode: MODE_OF_STORED[turn.mode] || turn.mode,
      turnId: null,
      feedback: 0,
      timestamp: turn.created_at,
    },
  ]
}

type State =
  | { status: 'loading' }
  | { status: 'ready'; conversation: SharedConversation }
  | { status: 'gone' }
  | { status: 'failed'; message: string }

interface SharedPageProps {
  theme?: Theme
  onTheme?: (theme: Theme) => void
}

/**
 * SharedPage — /shared/:token, one conversation as anyone with its link sees it: the questions,
 * the answers and their sources, read only. It needs no sign-in and says nothing of whose it is.
 */
export default function SharedPage({ theme = 'system', onTheme = () => {} }: SharedPageProps) {
  const { token = '' } = useParams()
  const [state, setState] = useState<State>({ status: 'loading' })

  useEffect(() => {
    let cancelled = false
    setState({ status: 'loading' })
    getSharedConversation(token)
      .then((conversation) => { if (!cancelled) setState({ status: 'ready', conversation }) })
      .catch((err) => {
        if (cancelled) return
        // 404: never made, or withdrawn. 422: not the shape of a link at all
        const gone = err instanceof ApiError && (err.status === 404 || err.status === 422)
        setState(gone ? { status: 'gone' } : { status: 'failed', message: err instanceof Error ? err.message : 'The conversation could not be loaded.' })
      })
    return () => { cancelled = true }
  }, [token])

  return (
    <>
      <AmbientField state="idle" />
      <div className="l-page h-page">
        <header className="l-top">
          <Link to="/" className="x-brand" title="Aether AI">
            <PrismMark /> Aether
          </Link>
          <Lens label="Theme" options={THEMES} value={theme} onChange={onTheme} />
        </header>

        <main className="x-column h-column">
          {state.status === 'loading' && <p className="p-hint" role="status">Loading the conversation</p>}

          {state.status === 'ready' && (
            <>
              <p className="p-eyebrow">Shared conversation · read only</p>
              {/* An unnamed conversation is titled by its first question, which is the next thing on the page */}
              <h1 className="p-h2">
                {state.conversation.title === state.conversation.turns[0]?.question ? 'A conversation shared with you' : state.conversation.title}
              </h1>
              {state.conversation.turns.flatMap(toMessages).map((message) => (
                <MessageBubble key={message.id} message={message} />
              ))}
              <footer className="h-foot">
                <p>You are reading a conversation someone shared. To ask questions of your own files, start here.</p>
                <Link to="/" className="p-btn p-btn--tonal">Ask your own documents</Link>
              </footer>
            </>
          )}

          {(state.status === 'gone' || state.status === 'failed') && (
            <div className="h-gone">
              <p className="p-eyebrow">Shared conversation</p>
              <h1 className="p-h2">{state.status === 'gone' ? 'This link no longer works.' : 'This conversation could not be loaded.'}</h1>
              <p>
                {state.status === 'gone'
                  ? 'The conversation was never shared by this link, or its owner has withdrawn it.'
                  : state.message}
              </p>
              <Link to="/" className="p-btn p-btn--filled">Go to the start page</Link>
            </div>
          )}
        </main>
      </div>
    </>
  )
}

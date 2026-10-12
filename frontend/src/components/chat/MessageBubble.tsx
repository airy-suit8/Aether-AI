import { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import type { Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { ClarityRing, SourceCard } from '../../design/prism'
import type { ClarityState } from '../../design/prism'
import type { FeedbackValue } from '../../services/api'
import type { AnswerMessage, ChatMessage } from './types'

// Model output is untrusted: no remote images (they can leak text in a URL), and links open elsewhere
const MARKDOWN: Components = {
  img: () => null,
  a: ({ node: _node, ...props }) => <a {...props} target="_blank" rel="noopener noreferrer" />,
}

// Similarity at or above this reads as grounded. From the first real run: relevant passages
// scored 0.67 to 0.80 and an unrelated question 0.50. To be calibrated on a dataset in Sprint 4.
const GROUNDED_AT = 0.6

function clarityOf(message: AnswerMessage): { state: ClarityState; value: number } | null {
  if (!message.sources?.length) return message.toolUsed ? null : { state: 'refused', value: 0 }
  const value = Math.max(0, Math.min(1, message.confidence || 0))
  return { state: value >= GROUNDED_AT ? 'grounded' : 'uncertain', value }
}

const RATINGS: { value: Exclude<FeedbackValue, 0>; label: string; path: string }[] = [
  { value: 1, label: 'Helpful', path: 'M6 8.5V15H3.5V8.5H6Zm0 0 3-5.5c1.2 0 2 .9 1.8 2.1L10.4 7.5h3.7c.9 0 1.6.9 1.4 1.8l-1.1 4.6c-.2.7-.8 1.1-1.5 1.1H6' },
  { value: -1, label: 'Not helpful', path: 'M6 9.5V3H3.5v6.5H6Zm0 0 3 5.5c1.2 0 2-.9 1.8-2.1l-.4-2.4h3.7c.9 0 1.6-.9 1.4-1.8l-1.1-4.6C13.2 3.4 12.6 3 11.9 3H6' },
]

/** Thumbs up and down for one answer. The chosen one is pressed; pressing it again takes it back. */
function Rating({ message, onRate }: { message: AnswerMessage; onRate: (message: AnswerMessage, value: FeedbackValue) => void }) {
  return (
    <div className="x-rate" role="group" aria-label="Rate this answer">
      {RATINGS.map(({ value, label, path }) => (
        <button
          key={value}
          type="button"
          className="p-icon-btn"
          aria-label={label}
          aria-pressed={message.feedback === value}
          title={message.feedback === value ? `${label} · press again to take it back` : label}
          onClick={() => onRate(message, message.feedback === value ? 0 : value)}
        >
          <svg width="18" height="18" viewBox="0 0 18 18" fill="none" aria-hidden="true">
            <path d={path} stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
          </svg>
        </button>
      ))}
    </div>
  )
}

interface MessageBubbleProps {
  message: ChatMessage
  isStreaming?: boolean
  streamingPhase?: string
  onRate?: (message: AnswerMessage, value: FeedbackValue) => void
}

/**
 * MessageBubble — one message. A question is a heading; an answer carries its clarity,
 * its text and, in the margin, the passages it came from. An answer the server saved (it has a
 * turn id) can be rated.
 */
export default function MessageBubble({ message, isStreaming = false, streamingPhase = '', onRate }: MessageBubbleProps) {
  const [active, setActive] = useState<number | null>(null)
  const [open, setOpen] = useState<number | null>(null)

  if (message.role === 'user') {
    return <h2 className="x-question">{message.content}</h2>
  }

  if (isStreaming) {
    return (
      <article className="x-exchange" aria-busy="true">
        <div>
          <div className="x-status">
            <span className="x-status__working" role="status">
              <i className="p-beam" aria-hidden="true" />
              {streamingPhase || 'Writing'}
            </span>
          </div>
          <p className="p-answer">
            {(message.content.match(/\s*\S+\s*/g) ?? []).map((word, index) => (
              <span key={index} className="p-word">{word}</span>
            ))}
          </p>
        </div>
      </article>
    )
  }

  const clarity = clarityOf(message)
  const sources = message.sources ?? []

  return (
    <article className="x-exchange">
      <div>
        <div className="x-status">
          {clarity && <ClarityRing value={clarity.value} state={clarity.state} />}
          {message.toolUsed && <span className="x-tool p-mono">tool · {message.toolUsed}</span>}
          {message.mode && <span className="p-mono">{message.mode} mode</span>}
        </div>
        <div className="p-answer">
          <ReactMarkdown remarkPlugins={[remarkGfm]} components={MARKDOWN}>
            {message.content}
          </ReactMarkdown>
        </div>
        {message.turnId != null && onRate && <Rating message={message} onRate={onRate} />}
      </div>

      {sources.length > 0 && (
        <aside className="x-margin">
          <p className="p-eyebrow">Sources</p>
          {sources.map((source, index) => (
            <SourceCard
              key={index}
              n={index + 1}
              source={source}
              order={index}
              dispersing
              active={active === index + 1}
              open={open === index + 1}
              onActivate={setActive}
              onToggle={() => setOpen(open === index + 1 ? null : index + 1)}
            />
          ))}
        </aside>
      )}
    </article>
  )
}

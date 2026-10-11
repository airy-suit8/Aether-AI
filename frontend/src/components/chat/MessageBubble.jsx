import React, { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { ClarityRing, SourceCard } from '../../design/prism'

// Model output is untrusted: no remote images (they can leak text in a URL), and links open elsewhere
const MARKDOWN = {
  img: () => null,
  a: ({ node: _node, ...props }) => <a {...props} target="_blank" rel="noopener noreferrer" />,
}

// Similarity at or above this reads as grounded. From the first real run: relevant passages
// scored 0.67 to 0.80 and an unrelated question 0.50. To be calibrated on a dataset in Sprint 4.
const GROUNDED_AT = 0.6

function clarityOf(message) {
  if (!message.sources?.length) return message.toolUsed ? null : { state: 'refused', value: 0 }
  const value = Math.max(0, Math.min(1, message.confidence || 0))
  return { state: value >= GROUNDED_AT ? 'grounded' : 'uncertain', value }
}

/**
 * MessageBubble — one message. A question is a heading; an answer carries its clarity,
 * its text and, in the margin, the passages it came from.
 */
export default function MessageBubble({ message, isStreaming = false }) {
  const [active, setActive] = useState(null)
  const [open, setOpen] = useState(null)

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
              {message.streamingPhase || 'Writing'}
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

import { createContext, memo, useCallback, useContext, useMemo, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import type { Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Cite, ClarityRing, SourceCard } from '../../design/prism'
import type { ClarityState } from '../../design/prism'
import type { FeedbackValue, Source, Usage } from '../../services/api'
import { remarkCitations } from './citations'
import type { AnswerMessage, ChatMessage } from './types'

// Similarity at or above this reads as grounded. From the first real run: relevant passages
// scored 0.67 to 0.80 and an unrelated question 0.50. To be calibrated on a dataset in Sprint 4.
const GROUNDED_AT = 0.6

function clarityOf(message: AnswerMessage): { state: ClarityState; value: number } | null {
  if (!message.sources?.length) return message.toolUsed ? null : { state: 'refused', value: 0 }
  const value = Math.max(0, Math.min(1, message.confidence || 0))
  return { state: value >= GROUNDED_AT ? 'grounded' : 'uncertain', value }
}

/** Which source card is lit or pinned open, shared by an answer's citation chips and its cards. */
interface CitationState {
  byNumber: ReadonlyMap<number, Source>
  active: number | null
  setActive: (n: number | null) => void
  toggle: (n: number) => void
}

const Citations = createContext<CitationState | null>(null)
const NO_SOURCES: Source[] = []

const describe = (n: number, source: Source) =>
  `Source ${n}: ${source.source}${source.page != null && source.page !== '?' ? `, page ${source.page}` : ''}`

/** A [n] in the answer, drawn as a Cite chip in the hue of source card n. */
function CitationMarker({ n }: { n: number }) {
  const citations = useContext(Citations)
  const source = citations?.byNumber.get(n)
  if (!citations || !source) return <>[{n}]</>
  return (
    <Cite
      n={n}
      label={describe(n, source)}
      active={citations.active === n}
      onActivate={citations.setActive}
      onClick={() => citations.toggle(n)}
    />
  )
}

// Model output is untrusted: no remote images (they can leak text in a URL), and links open
// elsewhere. A <cite> is made only by remarkCitations, never from the answer's own text.
const MARKDOWN: Components = {
  img: () => null,
  a: ({ node: _node, ...props }) => <a {...props} target="_blank" rel="noopener noreferrer" />,
  cite: ({ node }) => <CitationMarker n={Number(node?.properties?.dataN)} />,
}

/** The answer's Markdown. Memoised: lighting a source card does not parse the answer again. */
const AnswerText = memo(function AnswerText({ content, cited }: { content: string; cited: string }) {
  const plugins = useMemo(() => {
    const numbers = new Set(cited ? cited.split(',').map(Number) : [])
    return [remarkGfm, remarkCitations(numbers)]
  }, [cited])
  return (
    <div className="p-answer">
      <ReactMarkdown remarkPlugins={plugins} components={MARKDOWN}>
        {content}
      </ReactMarkdown>
    </div>
  )
})

// What the agent's tools are called in a sentence. tool_used joins their names with " + ";
// "agent_direct" means the agent used none.
const TOOL_NAMES: Record<string, string> = {
  document_search: 'Document search',
  calculator: 'Calculator',
  datetime: 'Date and time',
  agent_direct: 'None: it answered directly',
}

/** A labelled row naming the tools an agent answer used, in the order the server lists them. */
function ToolsUsed({ toolUsed }: { toolUsed: string }) {
  const tools = toolUsed.split('+').map((name) => name.trim()).filter(Boolean)
  return (
    <p className="x-tools">
      <span className="p-eyebrow">Tools used</span>
      {tools.map((name) => (
        <span key={name} className="x-tool">{TOOL_NAMES[name] ?? name.replace(/_/g, ' ')}</span>
      ))}
    </p>
  )
}

// What each stage of an answer is called on screen (the server's names: api/schemas.py, UsageStage)
const STAGE_NAMES: Record<string, string> = {
  rewrite: 'Rewriting the question',
  retrieve: 'Search',
  summarize: 'Summary',
  answer: 'Answer',
  agent: 'Agent',
  document_search: 'Document search',
}

const seconds = (s: number) => `${s.toFixed(1)} s`
const count = (n: number) => n.toLocaleString('en-US')

/**
 * What an answer cost, in one quiet line under it: "4.2 s, 1,240 tokens". Opening it lists the
 * stages in the order they ran. Tokens are what the model's API reported; they are never priced.
 */
function UsageLine({ usage }: { usage: Usage }) {
  const tokens = usage.input_tokens + usage.output_tokens
  return (
    <details className="x-usage">
      <summary>
        <span className="p-mono">{seconds(usage.seconds)}</span>, <span className="p-mono">{count(tokens)}</span> {tokens === 1 ? 'token' : 'tokens'}
      </summary>
      <ul aria-label="Stages">
        {usage.stages.map((stage, index) => (
          <li key={index}>
            <span>{STAGE_NAMES[stage.name] ?? stage.name.replace(/_/g, ' ')}</span>
            <span className="p-mono">{seconds(stage.seconds)}</span>
            <span className="p-mono">
              {stage.input_tokens + stage.output_tokens
                ? `${count(stage.input_tokens)} in, ${count(stage.output_tokens)} out`
                : 'no model call'}
            </span>
          </li>
        ))}
      </ul>
    </details>
  )
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
 *
 * Memoised (decision 15): while a later answer streams, the conversation re-renders with every
 * token, and a finished message, whose props have not changed, is skipped, Markdown and all.
 *
 * When the sources carry a number (the server's AETHER_ANSWER_FROM=chunks mode), each card is
 * numbered by it and each [n] in the answer is a Cite chip tied to card n: hovering or focusing
 * either lights both, and a chip pins its card open. Otherwise the cards are numbered in order
 * and the answer is shown as written.
 */
function MessageBubble({ message, isStreaming = false, streamingPhase = '', onRate }: MessageBubbleProps) {
  const [active, setActive] = useState<number | null>(null)
  const [open, setOpen] = useState<number | null>(null)
  const cardRefs = useRef<Record<number, HTMLButtonElement | null>>({})

  const sources = message.role === 'assistant' ? message.sources : NO_SOURCES
  const numbered = sources.length > 0 && sources.every((s) => typeof s.number === 'number')
  const numberOf = useCallback((source: Source, index: number) => (numbered && source.number != null ? source.number : index + 1), [numbered])
  const byNumber = useMemo(() => new Map(sources.map((s, i) => [numberOf(s, i), s])), [sources, numberOf])

  const toggle = useCallback((n: number) => {
    setOpen((current) => (current === n ? null : n))
    cardRefs.current[n]?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [])
  const citations = useMemo<CitationState>(() => ({ byNumber, active, setActive, toggle }), [byNumber, active, toggle])

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

  return (
    <Citations.Provider value={citations}>
      <article className="x-exchange">
        <div>
          <div className="x-status">
            {clarity && <ClarityRing value={clarity.value} state={clarity.state} />}
            {message.mode && <span className="p-mono">{message.mode} mode</span>}
          </div>
          {message.toolUsed && <ToolsUsed toolUsed={message.toolUsed} />}
          <AnswerText content={message.content} cited={numbered ? [...byNumber.keys()].join(',') : ''} />
          {message.turnId != null && onRate && <Rating message={message} onRate={onRate} />}
          {message.usage && <UsageLine usage={message.usage} />}
        </div>

        {sources.length > 0 && (
          <aside className="x-margin">
            <p className="p-eyebrow">Sources</p>
            {sources.map((source, index) => {
              const n = numberOf(source, index)
              return (
                <SourceCard
                  key={n}
                  n={n}
                  source={source}
                  order={index}
                  dispersing
                  active={active === n}
                  open={open === n}
                  onActivate={setActive}
                  onToggle={() => setOpen(open === n ? null : n)}
                  innerRef={(el) => { cardRefs.current[n] = el }}
                />
              )
            })}
          </aside>
        )}
      </article>
    </Citations.Provider>
  )
}

export default memo(MessageBubble)

import type { RefObject } from 'react'
import MessageBubble from './MessageBubble'
import type { FeedbackValue, Source } from '../../services/api'
import type { AnswerMessage, ChatMessage } from './types'

const IDEAS = ['Summarise the main points', 'List the key dates and numbers', 'What is still unclear or missing?']

/**
 * ChatWindow — the scrollable conversation. Each question is a heading; its answer and
 * evidence sit under it.
 */
interface ChatWindowProps {
  messages: ChatMessage[]
  streamingText: string
  streamingPhase: string
  isLoading: boolean
  threadLoading?: boolean
  streamRef: RefObject<HTMLDivElement | null>
  onScroll?: () => void
  hasDocuments: boolean
  onSuggest: (question: string) => void
  onRate?: (message: AnswerMessage, value: FeedbackValue) => void
  onOpenSource?: (source: Source, n: number) => void
}

export default function ChatWindow({ messages, streamingText, streamingPhase, isLoading, threadLoading = false, streamRef, onScroll, hasDocuments, onSuggest, onRate, onOpenSource }: ChatWindowProps) {
  // While a conversation is being loaded there is nothing to show yet, not even the empty state
  const isEmpty = messages.length === 0 && !streamingText && !isLoading && !threadLoading

  return (
    <div className="x-stream" ref={streamRef} onScroll={onScroll}>
      <div className="x-column" style={isEmpty ? { height: '100%' } : undefined}>
        {isEmpty ? (
          <div className="x-empty">
            <p className="p-eyebrow">{hasDocuments ? 'Your library is ready' : 'Start with a document'}</p>
            <h2 className="p-h2">{hasDocuments ? 'What do you want to know?' : 'Add a document to begin.'}</h2>
            <p>
              {hasDocuments
                ? 'Ask a question about your documents. Every answer shows the passages it came from, with the page and a similarity score.'
                : 'Add a document to your library on the left, then ask about it. Every answer shows the passages it came from.'}
            </p>
            {hasDocuments && (
              <div className="x-empty__ideas">
                {IDEAS.map((idea) => (
                  <button key={idea} type="button" className="p-btn p-btn--tonal" onClick={() => onSuggest(idea)}>
                    {idea}
                  </button>
                ))}
              </div>
            )}
          </div>
        ) : (
          <>
            {messages.map((msg) => (
              <MessageBubble key={msg.id} message={msg} onRate={onRate} onOpenSource={onOpenSource} />
            ))}

            {/* The reply in progress */}
            {(isLoading || streamingText) && (
              <MessageBubble
                message={{ id: 'streaming', role: 'assistant', content: streamingText, sources: [], confidence: null, toolUsed: null, mode: '', turnId: null, feedback: 0 }}
                streamingPhase={streamingPhase}
                isStreaming
              />
            )}
          </>
        )}
      </div>
    </div>
  )
}

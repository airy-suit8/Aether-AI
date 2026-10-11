import React from 'react'
import MessageBubble from './MessageBubble'

const IDEAS = ['Summarise the main points', 'List the key dates and numbers', 'What is still unclear or missing?']

/**
 * ChatWindow — the scrollable conversation. Each question is a heading; its answer and
 * evidence sit under it.
 */
export default function ChatWindow({ messages, streamingText, streamingPhase, isLoading, streamRef, hasDocuments, onSuggest }) {
  const isEmpty = messages.length === 0 && !streamingText && !isLoading

  return (
    <div className="x-stream" ref={streamRef}>
      <div className="x-column" style={isEmpty ? { height: '100%' } : undefined}>
        {isEmpty ? (
          <div className="x-empty">
            <p className="p-eyebrow">{hasDocuments ? 'Your library is ready' : 'Start with a document'}</p>
            <h2 className="p-display">
              Ask in white light.
              <br />
              Read the <em>spectrum.</em>
            </h2>
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
              <MessageBubble key={msg.id} message={msg} />
            ))}

            {/* The reply in progress */}
            {(isLoading || streamingText) && (
              <MessageBubble
                message={{ id: 'streaming', role: 'assistant', content: streamingText, streamingPhase }}
                isStreaming
              />
            )}
          </>
        )}
      </div>
    </div>
  )
}

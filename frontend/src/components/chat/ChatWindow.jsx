import React from 'react'
import MessageBubble from './MessageBubble'
import './ChatWindow.css'

/**
 * ChatWindow — Renders the scrollable conversation history
 */
export default function ChatWindow({ messages, streamingText, streamingPhase, isLoading, chatEndRef }) {
  const isEmpty = messages.length === 0 && !streamingText && !isLoading

  return (
    <div className="chat-window">
      {isEmpty ? (
        <div className="chat-empty-state scale-in">
          <div className="empty-icon">✦</div>
          <h2 className="empty-title">Welcome to Aether AI</h2>
          <p className="empty-subtitle">
            Upload your documents and start asking questions. Your knowledge base awaits.
          </p>
        </div>
      ) : (
        <div className="chat-message-list">
          {messages.map((msg) => (
            <MessageBubble key={msg.id} message={msg} />
          ))}

          {/* Active streaming / loading bubble */}
          {(isLoading || streamingText) && (
            <MessageBubble
              message={{
                id: 'streaming',
                role: 'assistant',
                content: streamingText,
                streamingPhase: streamingPhase,
              }}
              isStreaming={true}
            />
          )}

          <div ref={chatEndRef} style={{ height: '1px' }} />
        </div>
      )}
    </div>
  )
}

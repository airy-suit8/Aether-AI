import React from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import SourceCard from './SourceCard'
import ConfidenceBadge from './ConfidenceBadge'
import './MessageBubble.css'

/**
 * MessageBubble — Renders a single chat message (user or assistant)
 * Handles markdown rendering, tool use indication, confidence scoring, and source citations.
 */
export default function MessageBubble({ message, isStreaming = false }) {
  const isUser = message.role === 'user'
  
  if (isUser) {
    return (
      <div className="message-wrapper message-user slide-in-right">
        <div className="message-avatar user-avatar-msg">U</div>
        <div className="message-content-box">
          <div className="message-text">{message.content}</div>
        </div>
      </div>
    )
  }

  // Assistant Message
  return (
    <div className={`message-wrapper message-ai ${isStreaming && !message.content ? 'pulse' : 'slide-in-left'}`}>
      <div className="message-avatar ai-avatar-msg">✦</div>
      <div className="message-content-box">
        
        {/* Streaming / Reasoning Phase */}
        {isStreaming && message.streamingPhase && (
          <div className="message-phase">
            <span className="spinner spinner-sm" />
            {message.streamingPhase}
          </div>
        )}

        {/* Tool usage indicator (Agent Mode) */}
        {message.toolUsed && (
          <div className="message-tool">
            <span className="tool-icon">🛠️</span>
            Used Tool: <strong>{message.toolUsed}</strong>
          </div>
        )}

        {/* Content (Markdown) */}
        <div className="message-text markdown-content">
          {message.content ? (
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {message.content}
            </ReactMarkdown>
          ) : (
            isStreaming && !message.streamingPhase && (
              <div className="typing-indicator">
                <div className="typing-dot" />
                <div className="typing-dot" />
                <div className="typing-dot" />
              </div>
            )
          )}
        </div>

        {/* Sources & Confidence (Only render when complete and available) */}
        {!isStreaming && (message.sources?.length > 0 || message.confidence > 0) && (
          <div className="message-metadata fade-in">
            {message.confidence > 0 && (
              <ConfidenceBadge score={message.confidence} />
            )}
            
            {message.sources?.length > 0 && (
              <div className="sources-container">
                <div className="sources-label">Sources</div>
                <div className="sources-grid">
                  {message.sources.map((src, idx) => (
                    <SourceCard key={idx} source={src} />
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

      </div>
    </div>
  )
}

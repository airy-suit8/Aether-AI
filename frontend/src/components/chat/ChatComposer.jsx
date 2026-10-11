import React, { useState, useRef } from 'react'
import './ChatComposer.css'

export default function ChatComposer({
  onSend,
  isLoading,
  agentMode,
  langchainMode,
  streamingMode,
  hybridMode,
  onToggleAgent,
  onToggleLangchain,
  onToggleStreaming,
  onToggleHybrid,
  onUpload
}) {
  const [text, setText] = useState('')
  const fileInputRef = useRef(null)

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const handleSend = () => {
    if (text.trim() && !isLoading) {
      onSend(text)
      setText('')
    }
  }

  const handleFileChange = (e) => {
    const file = e.target.files[0]
    if (file) {
      onUpload(file)
      e.target.value = ''
    }
  }

  return (
    <div className="composer-wrapper">
      <div className="composer-container glass-strong">
        
        {/* Input Area */}
        <div className="composer-input-row">
          <textarea
            className="composer-textarea"
            placeholder="Ask anything about your private knowledge..."
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={isLoading}
            rows={1}
            style={{
              height: text ? `${Math.min(120, Math.max(24, text.split('\n').length * 24))}px` : '24px'
            }}
          />
        </div>

        {/* Actions Row */}
        <div className="composer-actions-row">
          
          <div className="composer-toggles">
            <button 
              className={`toggle-btn ${agentMode ? 'active' : ''}`}
              onClick={onToggleAgent}
              title="Agent Mode (ReAct Reasoning)"
            >
              🤖 Agent
            </button>
            <button 
              className={`toggle-btn ${langchainMode ? 'active' : ''}`}
              onClick={onToggleLangchain}
              title="LangChain LCEL Mode"
            >
              ⛓️ LangChain
            </button>
            <button 
              className={`toggle-btn ${streamingMode ? 'active' : ''}`}
              onClick={onToggleStreaming}
              disabled={agentMode} // Agents typically don't stream well token-by-token
              title={agentMode ? "Streaming disabled in Agent Mode" : "Stream Response"}
            >
              ⚡ Stream
            </button>
            <button 
              className={`toggle-btn ${hybridMode ? 'active' : ''}`}
              onClick={onToggleHybrid}
              disabled={agentMode || langchainMode}
              title="Hybrid Search (BM25 + Vector)"
            >
              🔀 Hybrid
            </button>
          </div>

          <div className="composer-primary-actions">
            <button 
              className="btn btn-ghost btn-icon composer-attach"
              onClick={() => fileInputRef.current?.click()}
              title="Attach Document"
            >
              📎
            </button>
            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf,.txt,.md,.markdown,.docx,.csv,.xlsx,.xls"
              onChange={handleFileChange}
              style={{ display: 'none' }}
            />
            
            <button 
              className="btn btn-primary btn-icon composer-send"
              onClick={handleSend}
              disabled={!text.trim() || isLoading}
            >
              {isLoading ? <span className="spinner spinner-sm" /> : '↑'}
            </button>
          </div>

        </div>
      </div>
    </div>
  )
}

import React, { useRef, useCallback } from 'react'
import './Sidebar.css'

/**
 * Sidebar — Navigation panel with branding, doc upload, file list, and settings.
 */
export default function Sidebar({
  isOpen,
  onToggle,
  documents,
  onUpload,
  uploadProgress,
  onNewThread,
  onOpenSettings,
  sessionId,
  onNavigateHome,
  agentMode,
  langchainMode,
  streamingMode,
}) {
  const fileInputRef = useRef(null)

  const handleFileChange = useCallback((e) => {
    const file = e.target.files[0]
    if (file) {
      onUpload(file)
      e.target.value = ''
    }
  }, [onUpload])

  const handleDrop = useCallback((e) => {
    e.preventDefault()
    e.currentTarget.classList.remove('drag-over')
    const file = e.dataTransfer.files[0]
    if (file) onUpload(file)
  }, [onUpload])

  const handleDragOver = useCallback((e) => {
    e.preventDefault()
    e.currentTarget.classList.add('drag-over')
  }, [])

  const handleDragLeave = useCallback((e) => {
    e.currentTarget.classList.remove('drag-over')
  }, [])

  return (
    <aside className={`sidebar glass-strong ${isOpen ? 'open' : 'closed'}`}>
      {/* Brand header */}
      <div className="sidebar-header">
        <div className="sidebar-brand" onClick={onNavigateHome} style={{ cursor: 'pointer' }}>
          <div className="sidebar-brand-icon">✦</div>
          <div className="sidebar-brand-text">
            <span className="sidebar-brand-name">Aether AI</span>
            <span className="sidebar-brand-version">v3.0</span>
          </div>
        </div>
        <button className="btn btn-ghost btn-icon sidebar-close" onClick={onToggle}>
          ◁
        </button>
      </div>

      {/* New thread button */}
      <div className="sidebar-new-thread">
        <button className="btn btn-primary new-thread-btn" onClick={onNewThread}>
          ✦ New Thread
        </button>
      </div>

      {/* Upload zone */}
      <div className="sidebar-section">
        <div className="sidebar-label">Document Uploader</div>
        <div
          className="upload-zone"
          onClick={() => fileInputRef.current?.click()}
          onDrop={handleDrop}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
        >
          {uploadProgress ? (
            <div className="upload-progress">
              <div className="spinner spinner-sm" />
              <span className="upload-progress-text">Ingesting {uploadProgress.filename}...</span>
            </div>
          ) : (
            <>
              <div className="upload-icon">📤</div>
              <div className="upload-label">Drop file or click to upload</div>
              <div className="upload-hint">PDF, DOCX, TXT, MD • Max 50MB</div>
            </>
          )}
        </div>
        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf,.txt,.md,.markdown,.docx"
          onChange={handleFileChange}
          style={{ display: 'none' }}
        />
      </div>

      {/* Document list */}
      <div className="sidebar-section sidebar-docs-section">
        <div className="sidebar-label">
          Ingested Files
          <span className="sidebar-count">{documents.length}</span>
        </div>
        <div className="sidebar-docs-list">
          {documents.length === 0 ? (
            <div className="sidebar-empty">No documents yet</div>
          ) : (
            documents.map((doc, i) => (
              <div key={i} className="sidebar-doc-item">
                <span className="doc-icon">
                  {doc.endsWith('.pdf') ? '📕' : doc.endsWith('.docx') ? '📘' : doc.endsWith('.md') || doc.endsWith('.markdown') ? '📝' : '📄'}
                </span>
                <span className="doc-name" title={doc}>{doc}</span>
              </div>
            ))
          )}
        </div>
      </div>

      {/* Mode indicators */}
      <div className="sidebar-section">
        <div className="sidebar-label">Active Modes</div>
        <div className="sidebar-modes">
          <div className={`mode-pill ${agentMode ? 'active' : ''}`}>🤖 Agent</div>
          <div className={`mode-pill ${langchainMode ? 'active' : ''}`}>⛓️ LangChain</div>
          <div className={`mode-pill ${streamingMode ? 'active' : ''}`}>⚡ Stream</div>
        </div>
      </div>

      {/* Footer */}
      <div className="sidebar-footer">
        <div className="sidebar-user">
          <div className="user-avatar">U</div>
          <div className="user-info">
            <div className="user-name">Developer</div>
            <div className="user-email">user@aether.ai</div>
          </div>
        </div>
        <button className="btn btn-ghost btn-icon" onClick={onOpenSettings} data-tooltip="Settings">
          ⚙️
        </button>
      </div>
    </aside>
  )
}

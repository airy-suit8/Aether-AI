import React, { useState } from 'react'
import './SourceCard.css'

export default function SourceCard({ source }) {
  const [expanded, setExpanded] = useState(false)

  // Determine icon based on filename
  const getIcon = (filename) => {
    if (!filename) return '📄'
    const name = filename.toLowerCase()
    if (name.endsWith('.pdf')) return '📕'
    if (name.endsWith('.docx')) return '📘'
    if (name.endsWith('.md') || name.endsWith('.txt')) return '📝'
    return '📄'
  }

  // Ensure content is formatted safely (no HTML injection)
  const sanitizeContent = (text) => {
    if (!text) return ''
    // Convert newlines to breaks or handle rendering safely
    // React handles basic sanitization, so we just return the string.
    return text
  }

  return (
    <div className={`source-card ${expanded ? 'expanded' : ''}`} onClick={() => setExpanded(!expanded)}>
      <div className="source-card-header">
        <div className="source-card-icon">{getIcon(source.source)}</div>
        <div className="source-card-title">{source.source || 'Unknown Source'}</div>
        <div className="source-card-meta">
          {source.page != null && source.page !== '?' && <span>p. {source.page}</span>}
          {typeof source.score === 'number' && <span title="Relevance score">{source.score.toFixed(2)}</span>}
        </div>
        <div className="source-card-expand">{expanded ? '−' : '+'}</div>
      </div>
      {expanded && (
        <div className="source-card-content">
          {sanitizeContent(source.snippet) || 'No preview available.'}
        </div>
      )}
    </div>
  )
}

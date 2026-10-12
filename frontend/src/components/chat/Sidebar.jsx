import React, { useRef, useCallback, useEffect, useState } from 'react'
import { useAuth } from '../../services/AuthContext'
import { PrismMark } from '../../design/prism'

const ACCEPT = '.pdf,.txt,.md,.markdown,.docx,.csv,.xlsx,.xls'
const DISARM_MS = 4000

const KINDS = { pdf: 'PDF', docx: 'DOC', txt: 'TXT', md: 'MD', markdown: 'MD', csv: 'CSV', xlsx: 'XLS', xls: 'XLS' }
const kindOf = (filename) => KINDS[filename.split('.').pop().toLowerCase()] || 'FILE'

/**
 * Sidebar — the library rail: brand, new thread, document drop zone, the user's documents, settings.
 */
export default function Sidebar({
  isOpen,
  onToggle,
  documents,
  onRemoveDocument,
  onUpload,
  uploadProgress,
  onNewThread,
  onOpenSettings,
  onNavigateHome,
}) {
  const fileInputRef = useRef(null)
  const [dragOver, setDragOver] = useState(false)
  const [armed, setArmed] = useState(null)       // id of the document one click from being removed
  const [removing, setRemoving] = useState(null) // id of the document being removed now
  const { username } = useAuth()

  // Several files are ingested one after another, so each gets its own progress and result
  const uploadAll = useCallback(async (fileList) => {
    for (const file of Array.from(fileList)) {
      await onUpload(file)
    }
  }, [onUpload])

  const handleFileChange = useCallback((e) => {
    const files = e.target.files
    if (files?.length) uploadAll(files)
    e.target.value = ''
  }, [uploadAll])

  const handleDrop = useCallback((e) => {
    e.preventDefault()
    setDragOver(false)
    if (e.dataTransfer.files?.length) uploadAll(e.dataTransfer.files)
  }, [uploadAll])

  // Removing a document takes two clicks on the same button: the first arms it ("Remove?"),
  // the second confirms. An armed button disarms after a few seconds or when focus leaves it.
  useEffect(() => {
    if (armed === null) return undefined
    const timer = setTimeout(() => setArmed(null), DISARM_MS)
    return () => clearTimeout(timer)
  }, [armed])

  const handleRemove = useCallback(async (doc) => {
    if (armed !== doc.id) {
      setArmed(doc.id)
      return
    }
    setArmed(null)
    setRemoving(doc.id)
    try {
      await onRemoveDocument(doc)
    } finally {
      setRemoving(null)
    }
  }, [armed, onRemoveDocument])

  return (
    <aside className="p-pane x-rail" aria-label="Library" aria-hidden={!isOpen}>
      <div className="x-rail__head">
        <button type="button" className="x-brand" onClick={onNavigateHome} title="Back to the start page">
          <PrismMark /> Aether
        </button>
        <button type="button" className="p-icon-btn" aria-label="Hide the library" onClick={onToggle}>
          <svg width="18" height="18" viewBox="0 0 18 18" fill="none" aria-hidden="true">
            <path d="M11 4 6 9l5 5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
      </div>

      <button type="button" className="p-btn p-btn--tonal" onClick={onNewThread}>New thread</button>

      <div>
        <button
          type="button"
          className="x-drop"
          data-over={dragOver}
          disabled={Boolean(uploadProgress)}
          onClick={() => fileInputRef.current?.click()}
          onDrop={handleDrop}
          onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
          onDragLeave={() => setDragOver(false)}
        >
          {uploadProgress ? (
            <>
              <b>Reading {uploadProgress.filename}</b>
              <i className="p-beam" aria-hidden="true" />
              <span>Splitting it into passages</span>
            </>
          ) : (
            <>
              <b>Add a document</b>
              <span>Drop files here, or click to choose</span>
              <span>PDF, Word, text, CSV, Excel · 50 MB max</span>
            </>
          )}
        </button>
        <input ref={fileInputRef} type="file" accept={ACCEPT} multiple hidden onChange={handleFileChange} />
      </div>

      <div className="x-library">
        <p className="p-eyebrow">
          <span>Library</span>
          <span>{documents.length}</span>
        </p>
        {documents.length === 0 ? (
          <p className="x-docs__empty">No documents yet</p>
        ) : (
          <ul className="x-docs">
            {documents.map((doc) => {
              const isArmed = armed === doc.id
              return (
                <li key={doc.id} className="x-doc" data-removing={removing === doc.id}>
                  <span className="x-doc__kind" aria-hidden="true">{kindOf(doc.filename)}</span>
                  <span className="x-doc__name" title={doc.filename}>{doc.filename}</span>
                  <button
                    type="button"
                    className="x-doc__remove"
                    data-armed={isArmed}
                    disabled={removing === doc.id}
                    aria-label={isArmed ? `Confirm removing ${doc.filename}` : `Remove ${doc.filename}`}
                    onClick={() => handleRemove(doc)}
                    onBlur={() => { if (isArmed) setArmed(null) }}
                  >
                    {isArmed ? 'Remove?' : (
                      <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
                        <path d="m3.5 3.5 7 7m0-7-7 7" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
                      </svg>
                    )}
                  </button>
                </li>
              )
            })}
          </ul>
        )}
      </div>

      <div className="x-user">
        <span className="x-avatar" aria-hidden="true">{(username || '?').charAt(0).toUpperCase()}</span>
        <span className="x-user__name">{username || 'Signed in'}</span>
        <button type="button" className="p-icon-btn" aria-label="Settings" onClick={onOpenSettings}>
          <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden="true">
            <path d="M3 6h7m4 0h3M3 14h3m4 0h7" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
            <circle cx="12" cy="6" r="2" stroke="currentColor" strokeWidth="1.7" />
            <circle cx="8" cy="14" r="2" stroke="currentColor" strokeWidth="1.7" />
          </svg>
        </button>
      </div>
    </aside>
  )
}

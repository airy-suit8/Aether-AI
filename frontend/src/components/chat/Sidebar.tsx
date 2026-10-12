import { useRef, useCallback, useEffect, useState } from 'react'
import type { ChangeEvent, DragEvent } from 'react'
import { Link } from 'react-router'
import { useAuth } from '../../services/AuthContext'
import type { DocumentRecord, SessionSummary } from '../../services/api'
import { PrismMark } from '../../design/prism'
import type { UploadProgress } from './types'

const ACCEPT = '.pdf,.txt,.md,.markdown,.docx,.csv,.xlsx,.xls'
const DISARM_MS = 4000

const KINDS: Record<string, string> = { pdf: 'PDF', docx: 'DOC', txt: 'TXT', md: 'MD', markdown: 'MD', csv: 'CSV', xlsx: 'XLS', xls: 'XLS' }
const kindOf = (filename: string) => KINDS[(filename.split('.').pop() ?? '').toLowerCase()] || 'FILE'

/** When a conversation was last used: the time today, the day and month before that. */
function formatWhen(iso: string): string {
  const when = new Date(iso)
  if (Number.isNaN(when.getTime())) return ''
  const today = new Date().toDateString() === when.toDateString()
  return today
    ? when.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
    : when.toLocaleDateString(undefined, { day: 'numeric', month: 'short' })
}

/**
 * A thread's name being edited in place. Enter or leaving the field keeps the name; Escape
 * gives up. Keys hand focus back to the row's Rename button (keyboard: true).
 */
function RenameField({ thread, onDone }: { thread: SessionSummary; onDone: (title: string | null, keyboard: boolean) => void }) {
  const [value, setValue] = useState(thread.title)
  const input = useRef<HTMLInputElement>(null)
  const finished = useRef(false)
  const finish = (title: string | null, keyboard: boolean) => {
    if (finished.current) return
    finished.current = true
    onDone(title, keyboard)
  }
  useEffect(() => {
    input.current?.focus()
    input.current?.select()
  }, [])
  return (
    <form className="x-thread x-thread--edit" onSubmit={(e) => { e.preventDefault(); finish(value, true) }}>
      <input
        ref={input}
        aria-label={`New name for ${thread.title}`}
        value={value}
        maxLength={200}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => { if (e.key === 'Escape') { e.preventDefault(); finish(null, true) } }}
        onBlur={() => finish(value, false)}
      />
    </form>
  )
}

/**
 * Sidebar — the library rail: brand, new thread, document drop zone, the user's documents, settings.
 */
interface SidebarProps {
  isOpen: boolean
  onToggle: () => void
  documents: DocumentRecord[]
  threads: SessionSummary[]
  currentThread: string | null
  onChooseThread: () => void
  onRenameThread: (thread: SessionSummary, title: string) => Promise<void>
  onDeleteThread: (thread: SessionSummary) => Promise<void>
  onRemoveDocument: (doc: DocumentRecord) => Promise<void>
  onUpload: (file: File) => Promise<void>
  uploadProgress: UploadProgress | null
  onNewThread: () => void
  onOpenSettings: () => void
  onNavigateHome: () => void
}

export default function Sidebar({
  isOpen,
  onToggle,
  documents,
  threads,
  currentThread,
  onChooseThread,
  onRenameThread,
  onDeleteThread,
  onRemoveDocument,
  onUpload,
  uploadProgress,
  onNewThread,
  onOpenSettings,
  onNavigateHome,
}: SidebarProps) {
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [dragOver, setDragOver] = useState(false)
  const [armed, setArmed] = useState<number | null>(null)       // id of the document one click from being removed
  const [removing, setRemoving] = useState<number | null>(null) // id of the document being removed now
  const [editing, setEditing] = useState<string | null>(null)        // the thread being renamed
  const [armedThread, setArmedThread] = useState<string | null>(null) // the thread one click from being deleted
  const [deleting, setDeleting] = useState<string | null>(null)       // the thread being deleted now
  const renameButtons = useRef<Record<string, HTMLButtonElement | null>>({})
  const { username } = useAuth()

  // Several files are ingested one after another, so each gets its own progress and result
  const uploadAll = useCallback(async (fileList: FileList) => {
    for (const file of Array.from(fileList)) {
      await onUpload(file)
    }
  }, [onUpload])

  const handleFileChange = useCallback((e: ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files
    if (files?.length) uploadAll(files)
    e.target.value = ''
  }, [uploadAll])

  const handleDrop = useCallback((e: DragEvent<HTMLButtonElement>) => {
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

  // A thread is deleted the same way: two clicks on its Delete button
  useEffect(() => {
    if (armedThread === null) return undefined
    const timer = setTimeout(() => setArmedThread(null), DISARM_MS)
    return () => clearTimeout(timer)
  }, [armedThread])

  const handleDeleteThread = useCallback(async (thread: SessionSummary) => {
    if (armedThread !== thread.session_id) {
      setArmedThread(thread.session_id)
      return
    }
    setArmedThread(null)
    setDeleting(thread.session_id)
    try {
      await onDeleteThread(thread)
    } finally {
      setDeleting(null)
    }
  }, [armedThread, onDeleteThread])

  const finishRename = useCallback((thread: SessionSummary, title: string | null, keyboard: boolean) => {
    setEditing(null)
    const name = title?.trim()
    if (name && name !== thread.title) onRenameThread(thread, name)
    if (keyboard) requestAnimationFrame(() => renameButtons.current[thread.session_id]?.focus())
  }, [onRenameThread])

  const handleRemove = useCallback(async (doc: DocumentRecord) => {
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

      <nav className="x-threads" aria-label="Conversations">
        <p className="p-eyebrow">
          <span>Threads</span>
          <span>{threads.length}</span>
        </p>
        {threads.length === 0 ? (
          <p className="x-docs__empty">No conversations yet</p>
        ) : (
          <ul className="x-thread-list">
            {threads.map((thread) => {
              const id = thread.session_id
              const isArmed = armedThread === id
              if (editing === id) {
                return (
                  <li key={id} className="x-thread-row">
                    <RenameField thread={thread} onDone={(title, keyboard) => finishRename(thread, title, keyboard)} />
                  </li>
                )
              }
              return (
                <li key={id} className="x-thread-row" data-armed={isArmed} data-removing={deleting === id}>
                  <Link
                    to={`/chat/${encodeURIComponent(id)}`}
                    className="x-thread"
                    aria-current={id === currentThread ? 'page' : undefined}
                    onClick={onChooseThread}
                  >
                    <span className="x-thread__title" title={thread.title}>{thread.title}</span>
                    <time className="p-mono" dateTime={thread.updated_at}>{formatWhen(thread.updated_at)}</time>
                  </Link>
                  <button
                    type="button"
                    className="x-doc__remove x-thread__act"
                    aria-label={`Rename ${thread.title}`}
                    ref={(el) => { renameButtons.current[id] = el }}
                    onClick={() => { setArmedThread(null); setEditing(id) }}
                  >
                    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
                      <path d="M8.5 3 11 5.5M2.5 11.5l.6-2.9 6.2-6.2a1.1 1.1 0 0 1 1.6 0l.7.7a1.1 1.1 0 0 1 0 1.6L5.4 10.9l-2.9.6Z" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" />
                    </svg>
                  </button>
                  <button
                    type="button"
                    className="x-doc__remove x-thread__act"
                    data-armed={isArmed}
                    disabled={deleting === id}
                    aria-label={isArmed ? `Confirm deleting ${thread.title}` : `Delete ${thread.title}`}
                    onClick={() => handleDeleteThread(thread)}
                    onBlur={() => { if (isArmed) setArmedThread(null) }}
                  >
                    {isArmed ? 'Delete?' : (
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
      </nav>

      {/* aria-live: the drop zone says how an upload is going, to a screen reader too */}
      <div aria-live="polite">
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
              <b>{uploadProgress.status === 'uploading' ? 'Sending' : 'Reading'} {uploadProgress.filename}</b>
              <i className="p-beam" aria-hidden="true" />
              <span>{uploadProgress.status === 'uploading' ? 'Uploading the file' : 'Splitting it into passages'}</span>
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
                  <span className="x-doc__label">
                    <span className="x-doc__name" title={doc.filename}>{doc.filename}</span>
                    {/* Uploads are read in the background; a word, not only a colour, says how it went */}
                    {doc.status === 'processing' && <span className="x-doc__state">Reading</span>}
                    {doc.status === 'failed' && (
                      <span className="x-doc__state" data-tone="bad" title={doc.error || undefined}>Could not be read</span>
                    )}
                  </span>
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

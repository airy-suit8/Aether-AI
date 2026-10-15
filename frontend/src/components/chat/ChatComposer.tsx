import { useEffect, useRef } from 'react'
import type { ChangeEvent } from 'react'
import { Aperture, Lens, Switch } from '../../design/prism'
import type { DocumentRecord, Mode } from '../../services/api'
import ScopePicker from './ScopePicker'
import type { Failure } from './types'

const MODES: { value: Mode; label: string }[] = [
  { value: 'default', label: 'Default' },
  { value: 'hybrid', label: 'Hybrid' },
  { value: 'agent', label: 'Agent' },
  { value: 'langchain', label: 'LangChain' },
]

const ACCEPT = '.pdf,.txt,.md,.markdown,.docx,.csv,.xlsx,.xls'

interface ChatComposerProps {
  onSend: (question: string) => void
  onStop: () => void
  onRetry: () => void
  failure: Failure | null
  restore: { text: string } | null
  isLoading: boolean
  mode: Mode
  onMode: (mode: Mode) => void
  streaming: boolean
  onStreaming: (streaming: boolean) => void
  onUpload: (file: File) => void
  documents?: DocumentRecord[]
  searchIn?: number[] | null
  onSearchIn?: (ids: number[] | null) => void
}

/**
 * ChatComposer — the dock: one answer mode, whether to stream, which documents to search in, and
 * the Aperture to ask through.
 * A reply that failed or was stopped is reported above it, in words, with a Retry action.
 */
export default function ChatComposer({
  onSend, onStop, onRetry, failure, restore, isLoading, mode, onMode, streaming, onStreaming, onUpload,
  documents = [], searchIn = null, onSearchIn = () => {},
}: ChatComposerProps) {
  const fileInputRef = useRef<HTMLInputElement>(null)
  const dockRef = useRef<HTMLDivElement>(null)

  // Toasts sit at the foot of the page, where the dock is: lift them above it, so a toast (or
  // several, when requests fail together) never covers the question box
  useEffect(() => {
    const dock = dockRef.current
    if (!dock) return undefined
    const root = document.documentElement
    const lift = () => root.style.setProperty('--p-toast-lift', `${dock.offsetHeight}px`)
    lift()
    const observer = new ResizeObserver(lift)
    observer.observe(dock)
    return () => {
      observer.disconnect()
      root.style.removeProperty('--p-toast-lift')
    }
  }, [])

  const handleFileChange = (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file) onUpload(file)
    e.target.value = ''
  }

  return (
    <div className="x-dock" ref={dockRef}>
      {failure && (
        <div className="x-retry" role="alert" data-tone={failure.stopped ? undefined : 'bad'}>
          <p><b>{failure.stopped ? 'Stopped.' : 'Failed.'}</b> {failure.message}</p>
          <button type="button" className="p-btn p-btn--tonal" onClick={onRetry} disabled={isLoading}>Retry</button>
        </div>
      )}
      <div className="x-dock__modes">
        <Lens label="Answer mode" options={MODES} value={mode} onChange={onMode} />
        <Switch
          label="Stream"
          checked={streaming}
          onChange={onStreaming}
          title={streaming ? 'Show the answer as it is written; it can be stopped' : 'Wait for the whole answer; it cannot be stopped'}
        />
        {documents.length > 1 && <ScopePicker documents={documents} value={searchIn} onChange={onSearchIn} />}
      </div>
      <Aperture
        busy={isLoading}
        onSend={onSend}
        // Only a stream can be stopped: closing it is the server's signal to save nothing
        onStop={streaming ? onStop : undefined}
        restore={restore}
        placeholder="Ask anything about your documents"
        leading={
          <>
            <button type="button" className="p-icon-btn" aria-label="Attach a document" onClick={() => fileInputRef.current?.click()}>
              <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden="true">
                <path d="M10 4v12M4 10h12" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
              </svg>
            </button>
            <input ref={fileInputRef} type="file" accept={ACCEPT} hidden onChange={handleFileChange} />
          </>
        }
      />
    </div>
  )
}

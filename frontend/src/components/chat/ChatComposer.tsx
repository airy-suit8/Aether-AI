import { useRef } from 'react'
import type { ChangeEvent } from 'react'
import { Aperture, Lens, Switch } from '../../design/prism'
import type { Mode } from '../../services/api'

const MODES: { value: Mode; label: string }[] = [
  { value: 'default', label: 'Default' },
  { value: 'hybrid', label: 'Hybrid' },
  { value: 'agent', label: 'Agent' },
  { value: 'langchain', label: 'LangChain' },
]

const ACCEPT = '.pdf,.txt,.md,.markdown,.docx,.csv,.xlsx,.xls'

/**
 * ChatComposer — the dock: one answer mode, whether to stream, and the Aperture to ask through.
 */
interface ChatComposerProps {
  onSend: (question: string) => void
  onStop: () => void
  isLoading: boolean
  mode: Mode
  onMode: (mode: Mode) => void
  streaming: boolean
  onStreaming: (streaming: boolean) => void
  onUpload: (file: File) => void
}

export default function ChatComposer({ onSend, onStop, isLoading, mode, onMode, streaming, onStreaming, onUpload }: ChatComposerProps) {
  const fileInputRef = useRef<HTMLInputElement>(null)

  const handleFileChange = (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file) onUpload(file)
    e.target.value = ''
  }

  return (
    <div className="x-dock">
      <div className="x-dock__modes">
        <Lens label="Answer mode" options={MODES} value={mode} onChange={onMode} />
        <Switch
          label="Stream"
          checked={streaming && mode !== 'agent'}
          onChange={onStreaming}
          disabled={mode === 'agent'}
          title={mode === 'agent' ? 'The agent answers in one piece' : 'Show the answer as it is written'}
        />
      </div>
      <Aperture
        busy={isLoading}
        onSend={onSend}
        onStop={onStop}
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

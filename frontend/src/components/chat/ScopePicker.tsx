import { useEffect, useId, useRef, useState } from 'react'
import type { DocumentRecord } from '../../services/api'

// What each kind of file is called in the menu, and in the button once chosen
const KIND_NAMES: Record<string, [string, string]> = {
  pdf: ['PDF', 'PDFs'],
  docx: ['Word file', 'Word files'],
  text: ['text file', 'text files'],
  csv: ['CSV file', 'CSV files'],
  xlsx: ['Excel file', 'Excel files'],
  xls: ['Excel file', 'Excel files'],
}

const nameOf = (doc: DocumentRecord) => doc.title || doc.filename
const short = (text: string, n = 30) => (text.length > n ? `${text.slice(0, n - 1).trimEnd()}…` : text)
const sameIds = (a: number[], b: number[]) => a.length === b.length && a.every((id) => b.includes(id))

/** The button's words for a choice: all, one document, every file of a kind, or a count. */
export function describeChoice(documents: DocumentRecord[], value: number[] | null): string {
  if (!value) return 'All documents'
  if (value.length === 1) {
    const doc = documents.find((d) => d.id === value[0])
    return doc ? short(nameOf(doc)) : '1 document'
  }
  for (const [kind, [singular]] of Object.entries(KIND_NAMES)) {
    const ofKind = documents.filter((d) => d.kind === kind).map((d) => d.id)
    if (ofKind.length > 1 && sameIds(ofKind, value)) return `Every ${singular}`
  }
  return `${value.length} documents`
}

interface ScopePickerProps {
  documents: DocumentRecord[]  // the documents that can be searched (ready)
  value: number[] | null       // the ids chosen; null: every document
  onChange: (value: number[] | null) => void
}

/**
 * ScopePicker — "Search in": every document, every file of one kind, or the documents ticked.
 * A choice applies to the questions that follow until it is changed. Without a choice, a
 * question can still name a document itself ("the PDF", "the Classification paper"); the answer
 * then says what it searched.
 */
export default function ScopePicker({ documents, value, onChange }: ScopePickerProps) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)
  const buttonRef = useRef<HTMLButtonElement>(null)
  const panelId = useId()

  // Escape or a click outside closes it; Escape gives the focus back to the button
  useEffect(() => {
    if (!open) return undefined
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setOpen(false)
        buttonRef.current?.focus()
      }
    }
    const onPointer = (e: PointerEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('keydown', onKey)
    document.addEventListener('pointerdown', onPointer)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('pointerdown', onPointer)
    }
  }, [open])

  const kinds = Object.entries(
    documents.reduce<Record<string, number[]>>((acc, d) => {
      if (d.kind && KIND_NAMES[d.kind]) (acc[d.kind] ??= []).push(d.id)
      return acc
    }, {}),
  ).filter(([, ids]) => ids.length > 0 && ids.length < documents.length)

  const toggle = (id: number) => {
    const chosen = value ?? []
    const next = chosen.includes(id) ? chosen.filter((x) => x !== id) : [...chosen, id]
    onChange(next.length ? next : null)
  }

  return (
    <div className="x-scope" ref={rootRef}>
      <button
        ref={buttonRef}
        type="button"
        className="p-btn x-scope__button"
        aria-expanded={open}
        aria-controls={panelId}
        data-chosen={value != null}
        onClick={() => setOpen((o) => !o)}
      >
        <span className="x-scope__label">Search in</span>{' '}
        <span className="x-scope__value">{describeChoice(documents, value)}</span>
        <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">
          <path d="M3 4.5 6 7.5 9 4.5" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>

      {open && (
        <div className="p-pane x-scope__panel" id={panelId} role="group" aria-label="Search in">
          <label className="x-scope__option">
            <input type="radio" name={`${panelId}-all`} checked={value == null} onChange={() => onChange(null)} />
            <span>All documents <span className="p-mono">{documents.length}</span></span>
          </label>

          {kinds.length > 0 && (
            <>
              <p className="p-eyebrow">By kind</p>
              {kinds.map(([kind, ids]) => (
                <label key={kind} className="x-scope__option">
                  <input type="radio" name={`${panelId}-all`} checked={value != null && sameIds(ids, value)} onChange={() => onChange(ids)} />
                  <span>Every {KIND_NAMES[kind][0]} <span className="p-mono">{ids.length}</span></span>
                </label>
              ))}
            </>
          )}

          <p className="p-eyebrow">Documents</p>
          {documents.map((doc) => (
            <label key={doc.id} className="x-scope__option x-scope__doc">
              <input type="checkbox" checked={value?.includes(doc.id) ?? false} onChange={() => toggle(doc.id)} />
              <span>
                <span className="x-scope__name">{nameOf(doc)}</span>
                {doc.title && <span className="x-scope__file p-mono">{doc.filename}</span>}
              </span>
            </label>
          ))}
        </div>
      )}
    </div>
  )
}

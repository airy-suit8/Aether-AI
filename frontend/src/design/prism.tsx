import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import type { CSSProperties, InputHTMLAttributes, KeyboardEvent, ReactNode, Ref, RefObject } from 'react'
import { usePointerLight } from './usePointerLight'
import { sourceHue } from './spectrum'
import './tokens.css'
import './prism.css'

/** Inline styles that set Prism's custom properties (--n, --hue, ...) as well as ordinary ones. */
export type PrismStyle = CSSProperties & Record<`--${string}`, string | number | undefined>

export type Theme = 'system' | 'dark'

/** Root of every Prism screen: sets the theme and makes the glass react to the pointer. */
export function PrismRoot({ theme = 'system', className = '', children }: { theme?: Theme; className?: string; children?: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null)
  usePointerLight(ref)
  return (
    <div ref={ref} className={`prism ${className}`} data-theme={theme === 'system' ? undefined : theme}>
      {children}
    </div>
  )
}

/** The mark: white light enters a prism and leaves as a spectrum. */
export function PrismMark({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" aria-hidden="true">
      <path d="M2 19.5 12.2 15" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      <path d="M19 14.2 30 9.5" stroke="var(--p-s1)" strokeWidth="1.6" strokeLinecap="round" />
      <path d="M19.6 16.6 30 15.4" stroke="var(--p-s3)" strokeWidth="1.6" strokeLinecap="round" />
      <path d="M20.2 19 30 21.3" stroke="var(--p-s5)" strokeWidth="1.6" strokeLinecap="round" />
      <path d="M16 5 26.5 26h-21L16 5Z" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
    </svg>
  )
}

export type FieldState = 'idle' | 'retrieving' | 'streaming'

/** Slow light behind the interface. state: idle | retrieving | streaming */
export function AmbientField({ state = 'idle' }: { state?: FieldState }) {
  return (
    <div className="p-field" data-state={state} aria-hidden="true">
      <i />
      <i />
      <i />
    </div>
  )
}

export interface LensOption<T extends string> {
  value: T
  label: string
}

/** One sliding control for a single choice. Arrow keys move the selection. */
export function Lens<T extends string>({ label, options, value, onChange }: {
  label: string
  options: readonly LensOption<T>[]
  value: T
  onChange: (value: T) => void
}) {
  const index = Math.max(0, options.findIndex((o) => o.value === value))

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const step = ({ ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 } as Record<string, number>)[event.key]
    if (!step) return
    event.preventDefault()
    const next = options[(index + step + options.length) % options.length]
    onChange(next.value)
    const buttons = event.currentTarget.querySelectorAll('button')
    buttons[(index + step + options.length) % options.length]?.focus()
  }

  const style: PrismStyle = { '--n': options.length, '--i': index }
  return (
    <div className="p-lens" role="radiogroup" aria-label={label} style={style} onKeyDown={onKeyDown}>
      <span className="p-lens__thumb" aria-hidden="true" />
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          role="radio"
          aria-checked={option.value === value}
          tabIndex={option.value === value ? 0 : -1}
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  )
}

export type ClarityState = 'grounded' | 'uncertain' | 'refused'

const CLARITY_LABEL: Record<ClarityState, string> = { grounded: 'Grounded', uncertain: 'Uncertain', refused: 'Not in your documents' }

/** Confidence as optical clarity: a sharp ring when grounded, a diffuse one when not. */
export function ClarityRing({ value = 0, state = 'grounded' }: { value?: number; state?: ClarityState }) {
  const percent = Math.round(value * 100)
  const text = state === 'refused' ? CLARITY_LABEL.refused : `${CLARITY_LABEL[state]} · ${percent}%`
  const style: PrismStyle = { '--v': state === 'refused' ? 0 : value }
  return (
    <span className="p-clarity" data-state={state} style={style}>
      <svg viewBox="0 0 30 30" role="img" aria-label={`Confidence: ${text}`}>
        <circle className="track" cx="15" cy="15" r="12" pathLength="1" />
        <circle className="halo" cx="15" cy="15" r="12" pathLength="1" />
        <circle className="arc" cx="15" cy="15" r="12" pathLength="1" />
      </svg>
      <span aria-hidden="true">
        {state === 'refused' ? CLARITY_LABEL.refused : (
          <>
            {CLARITY_LABEL[state]} <b className="p-mono">{percent}%</b>
          </>
        )}
      </span>
    </span>
  )
}

/**
 * The composer. Enter sends, Shift+Enter breaks the line; Send becomes Stop while busy (and stays
 * disabled while busy when there is no onStop). restore puts text back in it, such as a question
 * whose answer failed.
 */
export function Aperture({ busy = false, onSend, onStop, placeholder = 'Ask your documents', leading = null, restore = null }: {
  busy?: boolean
  onSend: (text: string) => void
  onStop?: () => void
  placeholder?: string
  leading?: ReactNode
  restore?: { text: string } | null
}) {
  const [text, setText] = useState('')
  const canSend = text.trim().length > 0

  useEffect(() => {
    if (restore) setText(restore.text)
  }, [restore])

  const send = () => {
    if (!canSend || busy) return
    onSend(text.trim())
    setText('')
  }

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== 'Enter' || event.shiftKey || event.nativeEvent.isComposing) return
    event.preventDefault()
    send()
  }

  return (
    <div className={`p-pane p-aperture${busy ? ' p-live' : ''}`}>
      {leading ?? <span />}
      <textarea
        rows={1}
        value={text}
        maxLength={5000}
        placeholder={placeholder}
        aria-label="Your question"
        readOnly={busy}
        onChange={(event) => setText(event.target.value)}
        onKeyDown={onKeyDown}
      />
      <button
        type="button"
        className="p-send"
        data-busy={busy}
        disabled={busy ? !onStop : !canSend}
        aria-label={busy ? 'Stop generating' : 'Send'}
        onClick={busy ? onStop : send}
      >
        <svg width="18" height="18" viewBox="0 0 18 18" fill="none" aria-hidden="true">
          <path d="M9 14.5v-11M4.5 8 9 3.5 13.5 8" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">
          <rect x="1.5" y="1.5" width="11" height="11" rx="2.5" fill="currentColor" />
        </svg>
      </button>
    </div>
  )
}

/** A citation marker in the answer: a small source of light in the colour of its source. */
export function Cite({ n, active = false, onActivate, onClick, label, innerRef }: {
  n: number
  active?: boolean
  onActivate: (n: number | null) => void
  onClick?: () => void
  label?: string
  innerRef?: Ref<HTMLButtonElement>
}) {
  const style: PrismStyle = { '--hue': sourceHue(n) }
  return (
    <button
      ref={innerRef}
      type="button"
      className="p-cite"
      data-active={active}
      style={style}
      aria-label={label ?? `Source ${n}`}
      onClick={onClick}
      onPointerEnter={() => onActivate(n)}
      onPointerLeave={() => onActivate(null)}
      onFocus={() => onActivate(n)}
      onBlur={() => onActivate(null)}
    >
      {n}
    </button>
  )
}

/** What a source card shows: the file, its page, the similarity score and the passage. */
export interface SourceView {
  source: string
  page?: number | string | null
  score?: number
  snippet?: string
}

/**
 * Evidence in the margin. Shows the file, the page, the similarity score and the passage.
 * Hover or focus lights it (onActivate); a click can pin it open (open + onToggle).
 */
export function SourceCard({ n, source, active = false, open = false, onActivate, onToggle, innerRef, order = 0, dispersing = false }: {
  n: number
  source: SourceView
  active?: boolean
  open?: boolean
  onActivate?: (n: number | null) => void
  onToggle?: () => void
  innerRef?: Ref<HTMLButtonElement>
  order?: number
  dispersing?: boolean
}) {
  const score = typeof source.score === 'number' ? source.score : 0
  const style: PrismStyle = { '--hue': sourceHue(n), '--score': Math.max(0, Math.min(1, score)), '--k': order }
  return (
    <button
      ref={innerRef}
      type="button"
      className={`p-pane p-source${dispersing ? ' p-disperse' : ''}`}
      data-active={active || open}
      style={style}
      aria-expanded={active || open}
      onClick={onToggle}
      onPointerEnter={() => onActivate?.(n)}
      onPointerLeave={() => onActivate?.(null)}
      onFocus={() => onActivate?.(n)}
      onBlur={() => onActivate?.(null)}
    >
      <span className="p-source__edge" aria-hidden="true" />
      <span className="p-source__head">
        <span className="p-source__n" aria-hidden="true">{n}</span>
        <span className="p-source__name" title={source.source}>{source.source}</span>
      </span>
      <span className="p-source__meta p-mono">
        {source.page != null && source.page !== '?' && <span>p. {source.page}</span>}
        <span className="p-source__bar" aria-hidden="true"><i /></span>
        <span title="Similarity to your question">{score.toFixed(2)}</span>
      </span>
      {source.snippet && <span className="p-source__text">{source.snippet}</span>}
    </button>
  )
}

/** A switch whose knob is a point of light. */
export function Switch({ label, checked, onChange, disabled = false, title }: {
  label: string
  checked: boolean
  onChange: (checked: boolean) => void
  disabled?: boolean
  title?: string
}) {
  return (
    <button
      type="button"
      role="switch"
      className="p-switch"
      aria-checked={checked}
      disabled={disabled}
      title={title}
      onClick={() => onChange(!checked)}
    >
      <span className="p-switch__track" aria-hidden="true" />
      {label}
    </button>
  )
}

type FieldProps = Omit<InputHTMLAttributes<HTMLInputElement>, 'value' | 'onChange'> & {
  label: string
  hint?: string
  error?: string
  value: string
  onChange: (value: string) => void
}

/** A text field: the label lifts on focus and the line beneath it splits into the spectrum. */
export function Field({ label, hint, error, value, onChange, type = 'text', ...rest }: FieldProps) {
  const id = useId()
  const note = error || hint
  return (
    <div className="p-field-wrap">
      <label className="p-input" data-invalid={Boolean(error)}>
        <input
          type={type}
          value={value}
          placeholder=" "
          aria-invalid={Boolean(error)}
          aria-describedby={note ? `${id}-note` : undefined}
          onChange={(event) => onChange(event.target.value)}
          {...rest}
        />
        <span>{label}</span>
      </label>
      {note && (
        <p id={`${id}-note`} className="p-hint" data-tone={error ? 'bad' : undefined} role={error ? 'alert' : undefined}>
          {note}
        </p>
      )}
    </div>
  )
}

/** For actions that cannot be undone: nothing happens unless the press is held. */
export function HoldButton({ onConfirm, holdMs = 1200, disabled = false, children }: {
  onConfirm: () => void
  holdMs?: number
  disabled?: boolean
  children?: ReactNode
}) {
  const [holding, setHolding] = useState(false)
  const timer = useRef(0)

  const cancel = () => {
    window.clearTimeout(timer.current)
    setHolding(false)
  }

  const start = () => {
    if (disabled || holding) return
    setHolding(true)
    timer.current = window.setTimeout(() => {
      setHolding(false)
      onConfirm()
    }, holdMs)
  }

  useEffect(() => () => window.clearTimeout(timer.current), [])

  const style: PrismStyle = { '--hold-ms': `${holdMs}ms` }
  return (
    <button
      type="button"
      className="p-btn p-hold"
      data-holding={holding}
      style={style}
      disabled={disabled}
      onPointerDown={start}
      onPointerUp={cancel}
      onPointerLeave={cancel}
      onBlur={cancel}
      onKeyDown={(event) => {
        if ((event.key === ' ' || event.key === 'Enter') && !event.repeat) start()
      }}
      onKeyUp={cancel}
    >
      <span>{children}</span>
    </button>
  )
}

/**
 * Make everything outside `node` inert, up to the Prism root, and return how to undo it. Live
 * regions (the toasts) stay as they are, so what they say is still heard.
 */
function inertAround(node: HTMLElement): () => void {
  const made: Element[] = []
  let child: HTMLElement = node
  while (child.parentElement) {
    const parent: HTMLElement = child.parentElement
    for (const sibling of parent.children) {
      if (sibling === child || sibling.hasAttribute('inert') || sibling.matches('[aria-live]')) continue
      sibling.setAttribute('inert', '')
      made.push(sibling)
    }
    if (parent.classList.contains('prism')) break
    child = parent
  }
  return () => made.forEach((el) => el.removeAttribute('inert'))
}

/**
 * A modal sheet of glass. Escape and a click outside close it; Tab stays inside it; and the page
 * behind it is inert while it is open, so neither focus nor a screen reader can wander there.
 */
export function Dialog({ title, onClose, width, children }: {
  title: string
  onClose: () => void
  width?: string
  children?: ReactNode
}) {
  const ref = useRef<HTMLDivElement>(null)
  const scrimRef = useRef<HTMLDivElement>(null)
  // What had focus when the dialog opened, read before anything is made inert (which would move it)
  const [returnTo] = useState(() => document.activeElement)

  // On opening: the page behind becomes inert and focus moves in; on closing, both are undone
  useEffect(() => {
    const node = ref.current
    const scrim = scrimRef.current
    if (!node || !scrim) return undefined
    const undoInert = inertAround(scrim)
    ;(node.querySelector<HTMLElement>('input, select, textarea') ?? node).focus()
    return () => {
      undoInert()
      if (returnTo instanceof HTMLElement) returnTo.focus()
    }
  }, [returnTo])

  useEffect(() => {
    const node = ref.current
    if (!node) return undefined
    const focusables = () => [...node.querySelectorAll<HTMLElement>('a[href], button:not(:disabled), input, select, textarea, [tabindex="0"]')]

    const onKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key === 'Escape') {
        onClose()
        return
      }
      if (event.key !== 'Tab') return
      const items = focusables()
      if (items.length === 0) return
      const first = items[0]
      const last = items[items.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }

    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [onClose])

  const style: PrismStyle | undefined = width ? { '--dialog-w': width } : undefined
  return (
    <div
      ref={scrimRef}
      className="p-scrim"
      onPointerDown={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <div
        ref={ref}
        className="p-pane p-dialog"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        style={style}
      >
        <header className="p-dialog__head">
          <h2>{title}</h2>
          <button type="button" className="p-icon-btn" aria-label="Close" onClick={onClose}>
            <svg width="18" height="18" viewBox="0 0 18 18" fill="none" aria-hidden="true">
              <path d="m4.5 4.5 9 9m0-9-9 9" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
            </svg>
          </button>
        </header>
        {children}
      </div>
    </div>
  )
}

export interface ThreadPair {
  n: number
  from: Element | null | undefined
  to: Element | null | undefined
  edge?: Element | null
}

/**
 * Lines of light from each citation to its source card.
 *
 * getPairs returns [{ n, from: Element, to: Element, edge?: Element }]. A thread leaves at
 * the height of its citation but from the right edge of `edge` (the answer text), so it
 * runs through the gutter and never strikes through a line of text. Positions are measured
 * against containerRef, so the SVG must be a child of that container. Paths use
 * pathLength=1, which lets CSS draw them with a single dash without measuring their length.
 */
export function Threads({ containerRef, getPairs, active = null, epoch = 0 }: {
  containerRef: RefObject<HTMLElement | null>
  getPairs: () => ThreadPair[]
  active?: number | null
  epoch?: number
}) {
  const [paths, setPaths] = useState<{ n: number; d: string }[]>([])

  const measure = useCallback(() => {
    const container = containerRef.current
    if (!container) return
    const box = container.getBoundingClientRect()
    const next: { n: number; d: string }[] = []
    for (const { n, from, to, edge } of getPairs()) {
      if (!from || !to) continue
      const a = from.getBoundingClientRect()
      const b = to.getBoundingClientRect()
      const x1 = (edge ? edge.getBoundingClientRect().right + 10 : a.right + 2) - box.left
      const y1 = a.top + a.height / 2 - box.top
      const x2 = b.left - box.left
      const y2 = b.top + Math.min(b.height / 2, 30) - box.top
      if (x2 - x1 < 28) continue // stacked layout: the card is below the text, no room for a thread
      const bend = (x2 - x1) * 0.55
      next.push({ n, d: `M${x1},${y1} C${x1 + bend},${y1} ${x2 - bend},${y2} ${x2},${y2}` })
    }
    setPaths(next)
  }, [containerRef, getPairs])

  useLayoutEffect(() => {
    measure()
    const container = containerRef.current
    const observer = new ResizeObserver(measure)
    if (container) observer.observe(container)
    window.addEventListener('resize', measure)
    return () => {
      observer.disconnect()
      window.removeEventListener('resize', measure)
    }
  }, [measure, containerRef, epoch])

  return (
    <svg className="p-threads" data-dim={active != null} aria-hidden="true">
      {paths.map((path, k) => {
        const style: PrismStyle = { '--hue': sourceHue(path.n), '--k': k }
        return (
          <path
            key={`${epoch}-${path.n}`}
            d={path.d}
            pathLength="1"
            data-active={active === path.n}
            style={style}
          />
        )
      })}
    </svg>
  )
}


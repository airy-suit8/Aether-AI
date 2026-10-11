import React, { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import { usePointerLight } from './usePointerLight'
import { sourceHue } from './spectrum'
import './tokens.css'
import './prism.css'

/** Root of every Prism screen: sets the theme and makes the glass react to the pointer. */
export function PrismRoot({ theme = 'system', className = '', children }) {
  const ref = useRef(null)
  usePointerLight(ref)
  return (
    <div ref={ref} className={`prism ${className}`} data-theme={theme === 'system' ? undefined : theme}>
      {children}
    </div>
  )
}

/** The mark: white light enters a prism and leaves as a spectrum. */
export function PrismMark({ size = 28 }) {
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

/** Slow light behind the interface. state: idle | retrieving | streaming */
export function AmbientField({ state = 'idle' }) {
  return (
    <div className="p-field" data-state={state} aria-hidden="true">
      <i />
      <i />
      <i />
    </div>
  )
}

/** One sliding control for a single choice. Arrow keys move the selection. */
export function Lens({ label, options, value, onChange }) {
  const index = Math.max(0, options.findIndex((o) => o.value === value))

  const onKeyDown = (event) => {
    const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[event.key]
    if (!step) return
    event.preventDefault()
    const next = options[(index + step + options.length) % options.length]
    onChange(next.value)
    const buttons = event.currentTarget.querySelectorAll('button')
    buttons[(index + step + options.length) % options.length]?.focus()
  }

  return (
    <div
      className="p-lens"
      role="radiogroup"
      aria-label={label}
      style={{ '--n': options.length, '--i': index }}
      onKeyDown={onKeyDown}
    >
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

const CLARITY_LABEL = { grounded: 'Grounded', uncertain: 'Uncertain', refused: 'Not in your documents' }

/** Confidence as optical clarity: a sharp ring when grounded, a diffuse one when not. */
export function ClarityRing({ value = 0, state = 'grounded' }) {
  const percent = Math.round(value * 100)
  const text = state === 'refused' ? CLARITY_LABEL.refused : `${CLARITY_LABEL[state]} · ${percent}%`
  return (
    <span className="p-clarity" data-state={state} style={{ '--v': state === 'refused' ? 0 : value }}>
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

/** The composer. Enter sends, Shift+Enter breaks the line; Send becomes Stop while busy. */
export function Aperture({ busy = false, onSend, onStop, placeholder = 'Ask your documents', leading = null }) {
  const [text, setText] = useState('')
  const canSend = text.trim().length > 0

  const send = () => {
    if (!canSend || busy) return
    onSend(text.trim())
    setText('')
  }

  const onKeyDown = (event) => {
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
        disabled={!busy && !canSend}
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
export function Cite({ n, active = false, onActivate, innerRef }) {
  return (
    <button
      ref={innerRef}
      type="button"
      className="p-cite"
      data-active={active}
      style={{ '--hue': sourceHue(n) }}
      aria-label={`Source ${n}`}
      onPointerEnter={() => onActivate(n)}
      onPointerLeave={() => onActivate(null)}
      onFocus={() => onActivate(n)}
      onBlur={() => onActivate(null)}
    >
      {n}
    </button>
  )
}

/**
 * Evidence in the margin. Shows the file, the page, the similarity score and the passage.
 * Hover or focus lights it (onActivate); a click can pin it open (open + onToggle).
 */
export function SourceCard({ n, source, active = false, open = false, onActivate, onToggle, innerRef, order = 0, dispersing = false }) {
  const score = typeof source.score === 'number' ? source.score : 0
  return (
    <button
      ref={innerRef}
      type="button"
      className={`p-pane p-source${dispersing ? ' p-disperse' : ''}`}
      data-active={active || open}
      style={{ '--hue': sourceHue(n), '--score': Math.max(0, Math.min(1, score)), '--k': order }}
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
export function Switch({ label, checked, onChange, disabled = false, title }) {
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

/** A text field: the label lifts on focus and the line beneath it splits into the spectrum. */
export function Field({ label, hint, error, value, onChange, type = 'text', ...rest }) {
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
export function HoldButton({ onConfirm, holdMs = 1200, disabled = false, children }) {
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

  return (
    <button
      type="button"
      className="p-btn p-hold"
      data-holding={holding}
      style={{ '--hold-ms': `${holdMs}ms` }}
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

/** A modal sheet of glass. Escape and a click outside close it; Tab stays inside it. */
export function Dialog({ title, onClose, width, children }) {
  const ref = useRef(null)

  useEffect(() => {
    const node = ref.current
    const previous = document.activeElement
    const focusables = () => [...node.querySelectorAll('a[href], button:not(:disabled), input, select, textarea, [tabindex="0"]')]
    ;(node.querySelector('input, select, textarea') ?? node).focus()

    const onKeyDown = (event) => {
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
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      if (previous instanceof HTMLElement) previous.focus()
    }
  }, [onClose])

  return (
    <div
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
        style={width ? { '--dialog-w': width } : undefined}
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

/**
 * Lines of light from each citation to its source card.
 *
 * getPairs returns [{ n, from: Element, to: Element, edge?: Element }]. A thread leaves at
 * the height of its citation but from the right edge of `edge` (the answer text), so it
 * runs through the gutter and never strikes through a line of text. Positions are measured
 * against containerRef, so the SVG must be a child of that container. Paths use
 * pathLength=1, which lets CSS draw them with a single dash without measuring their length.
 */
export function Threads({ containerRef, getPairs, active = null, epoch = 0 }) {
  const [paths, setPaths] = useState([])

  const measure = useCallback(() => {
    const container = containerRef.current
    if (!container) return
    const box = container.getBoundingClientRect()
    const next = []
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
      {paths.map((path, k) => (
        <path
          key={`${epoch}-${path.n}`}
          d={path.d}
          pathLength="1"
          data-active={active === path.n}
          style={{ '--hue': sourceHue(path.n), '--k': k }}
        />
      ))}
    </svg>
  )
}

import { useCallback, useEffect, useRef, useState } from 'react'
import { Cite, Threads } from '../../design/prism'
import type { PrismStyle } from '../../design/prism'
import { sourceHue } from '../../design/spectrum'

/** What sets the app apart. Each claim has the thing that backs it, as every answer in the app does. */
const POINTS = [
  {
    claim: 'It shows where every answer came from.',
    title: 'Beside every answer',
    evidence: 'The file, the page, how closely the passage matched your question, and the passage itself.',
  },
  {
    claim: 'It tells you when your documents do not hold the answer.',
    title: 'Not found, said plainly',
    evidence: 'A question your files cannot answer gets a refusal with no sources attached, not an invented reply.',
  },
  {
    claim: 'What you upload stays yours.',
    title: 'One account, one library',
    evidence: 'Every search is limited to the documents of the account that is signed in. Remove a document and its passages go with it.',
  },
  {
    claim: 'It reads the files an office really uses.',
    title: 'PDF, Word, Excel, CSV, text',
    evidence: 'Tables inside Word files, every sheet of a workbook, and codes that start with zeros arrive as they were written.',
  },
  {
    claim: 'It was built to be checked, not just believed.',
    title: 'Tested and audited',
    evidence: 'Every change passes an automated test suite before it is merged, and the whole project has been audited twice.',
  },
]

// The trace: one claim after another is joined to its evidence, each held for a moment
const TRACE_STEP_MS = 720
const TRACE_REST_MS = 900

const prefersStillness = () =>
  typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches

/**
 * WhyDifferent — the start page's argument, made the way the app makes every answer: a claim,
 * a numbered marker, and the evidence for it in the margin, joined by a thread of its colour.
 * Nothing here is sample data: each card says what in the product backs the claim.
 *
 * The threads are the point of it. When the claims scroll into view they are traced once,
 * one claim at a time, each lighting its evidence as its line is drawn; then all five stay.
 * Pointing at a claim, its marker or its card takes over from the trace at any moment.
 */
export default function WhyDifferent() {
  const [active, setActive] = useState<number | null>(null)
  const [traced, setTraced] = useState<number | null>(null)  // the claim the trace is on now
  const [drawn, setDrawn] = useState(0)                      // how many threads are drawn so far
  const [epoch, setEpoch] = useState(0)
  const benchRef = useRef<HTMLDivElement>(null)
  const claimsRef = useRef<HTMLOListElement>(null)
  const citeRefs = useRef<Record<number, HTMLButtonElement | null>>({})
  const cardRefs = useRef<Record<number, HTMLDivElement | null>>({})
  const timers = useRef<number[]>([])
  const ledRef = useRef(false)  // the reader has pointed at something: the trace does not start, or stops

  const stopTrace = useCallback(() => {
    ledRef.current = true
    timers.current.forEach((id) => window.clearTimeout(id))
    timers.current = []
    setTraced(null)
    setDrawn(POINTS.length)
  }, [])

  // Measure the threads once the page has laid out with its fonts
  useEffect(() => {
    let cancelled = false
    const redraw = () => { if (!cancelled) setEpoch((n) => n + 1) }
    document.fonts?.ready.then(redraw)
    redraw()
    return () => { cancelled = true }
  }, [])

  // Trace the threads the first time the claims are seen. Without an observer, or for someone
  // who asked for less motion, they are simply all there. So are they on a narrow screen, where
  // the evidence is below the claims and no thread is drawn: there is nothing to trace.
  useEffect(() => {
    const claims = claimsRef.current
    if (!claims || typeof IntersectionObserver !== 'function' || prefersStillness()) {
      setDrawn(POINTS.length)
      return undefined
    }
    const observer = new IntersectionObserver((entries) => {
      if (!entries.some((entry) => entry.isIntersecting)) return
      observer.disconnect()
      if (ledRef.current) return
      if (!benchRef.current?.querySelector('.p-threads path')) {
        setDrawn(POINTS.length)
        return
      }
      POINTS.forEach((_, i) => {
        timers.current.push(window.setTimeout(() => {
          setDrawn(i + 1)
          setTraced(i + 1)
        }, i * TRACE_STEP_MS))
      })
      timers.current.push(window.setTimeout(() => setTraced(null), (POINTS.length - 1) * TRACE_STEP_MS + TRACE_REST_MS))
    }, { threshold: 0.5 })
    observer.observe(claims)
    return () => {
      observer.disconnect()
      timers.current.forEach((id) => window.clearTimeout(id))
      timers.current = []
    }
  }, [])

  const getPairs = useCallback(
    () => POINTS.map((_, i) => ({ n: i + 1, from: citeRefs.current[i + 1], to: cardRefs.current[i + 1], edge: claimsRef.current })),
    [],
  )

  // Pointing at something ends the trace: the reader leads from here
  const point = useCallback((n: number | null) => {
    if (n != null) stopTrace()
    setActive(n)
  }, [stopTrace])

  // On a narrow screen the evidence is below the claims: a tap on a marker brings its card into view
  const reveal = (n: number) => {
    point(n)
    cardRefs.current[n]?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }

  const lit = active ?? traced

  return (
    <section className="p-pane l-why" aria-labelledby="why-title">
      <div className="l-why__bench" ref={benchRef}>
        <div>
          <p className="p-eyebrow">Why it is different</p>
          <h2 id="why-title" className="p-h2">Five claims, and what stands behind each.</h2>
          <p className="l-why__lede">
            Aether never asks you to take its word for anything. So neither does this page: follow each claim to what backs it.
          </p>
          <ol className="l-claims" ref={claimsRef} data-dim={lit != null}>
            {POINTS.map((point_, i) => {
              const n = i + 1
              return (
                <li
                  key={point_.title}
                  className="l-claim"
                  data-active={lit === n}
                  onPointerEnter={() => point(n)}
                  onPointerLeave={() => point(null)}
                >
                  {point_.claim}
                  <Cite
                    n={n}
                    active={lit === n}
                    onActivate={point}
                    onClick={() => reveal(n)}
                    label={`Evidence ${n}: ${point_.title}`}
                    innerRef={(el) => { citeRefs.current[n] = el }}
                  />
                </li>
              )
            })}
          </ol>
        </div>

        <aside className="l-why__margin" aria-label="Evidence">
          <p className="p-eyebrow">Evidence</p>
          {POINTS.map((point_, i) => {
            const n = i + 1
            const style: PrismStyle = { '--hue': sourceHue(n) }
            return (
              <div
                key={point_.title}
                ref={(el) => { cardRefs.current[n] = el }}
                className="p-pane p-source l-proof"
                data-active={lit === n}
                style={style}
                onPointerEnter={() => point(n)}
                onPointerLeave={() => point(null)}
              >
                <span className="p-source__edge" aria-hidden="true" />
                <span className="p-source__head">
                  <span className="p-source__n" aria-hidden="true">{n}</span>
                  <span className="p-source__name">{point_.title}</span>
                </span>
                <span className="p-source__text">{point_.evidence}</span>
              </div>
            )
          })}
        </aside>

        <Threads containerRef={benchRef} getPairs={getPairs} active={lit} epoch={epoch} drawn={drawn} />
      </div>
    </section>
  )
}

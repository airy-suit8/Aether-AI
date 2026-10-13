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

/**
 * WhyDifferent — the start page's argument, made the way the app makes every answer: a claim,
 * a numbered marker, and the evidence for it in the margin, joined by a thread of its colour.
 * Nothing here is sample data: each card says what in the product backs the claim.
 */
export default function WhyDifferent() {
  const [active, setActive] = useState<number | null>(null)
  const [epoch, setEpoch] = useState(0)
  const benchRef = useRef<HTMLDivElement>(null)
  const claimsRef = useRef<HTMLOListElement>(null)
  const citeRefs = useRef<Record<number, HTMLButtonElement | null>>({})
  const cardRefs = useRef<Record<number, HTMLDivElement | null>>({})

  // Measure the threads once the page has laid out with its fonts
  useEffect(() => {
    let cancelled = false
    const redraw = () => { if (!cancelled) setEpoch((n) => n + 1) }
    document.fonts?.ready.then(redraw)
    redraw()
    return () => { cancelled = true }
  }, [])

  const getPairs = useCallback(
    () => POINTS.map((_, i) => ({ n: i + 1, from: citeRefs.current[i + 1], to: cardRefs.current[i + 1], edge: claimsRef.current })),
    [],
  )

  // On a narrow screen the evidence is below the claims: a tap on a marker brings its card into view
  const reveal = (n: number) => {
    setActive(n)
    cardRefs.current[n]?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }

  return (
    <section className="p-pane l-why" aria-labelledby="why-title">
      <div className="l-why__bench" ref={benchRef}>
        <div>
          <p className="p-eyebrow">Why it is different</p>
          <h2 id="why-title" className="p-h2">Five claims, and what stands behind each.</h2>
          <p className="l-why__lede">
            Aether never asks you to take its word for anything. So neither does this page: point at a number to see what backs the claim.
          </p>
          <ol className="l-claims" ref={claimsRef} data-dim={active != null}>
            {POINTS.map((point, i) => {
              const n = i + 1
              return (
                <li
                  key={point.title}
                  className="l-claim"
                  data-active={active === n}
                  onPointerEnter={() => setActive(n)}
                  onPointerLeave={() => setActive(null)}
                >
                  {point.claim}
                  <Cite
                    n={n}
                    active={active === n}
                    onActivate={setActive}
                    onClick={() => reveal(n)}
                    label={`Evidence ${n}: ${point.title}`}
                    innerRef={(el) => { citeRefs.current[n] = el }}
                  />
                </li>
              )
            })}
          </ol>
        </div>

        <aside className="l-why__margin" aria-label="Evidence">
          <p className="p-eyebrow">Evidence</p>
          {POINTS.map((point, i) => {
            const n = i + 1
            const style: PrismStyle = { '--hue': sourceHue(n) }
            return (
              <div
                key={point.title}
                ref={(el) => { cardRefs.current[n] = el }}
                className="p-pane p-source l-proof"
                data-active={active === n}
                style={style}
                onPointerEnter={() => setActive(n)}
                onPointerLeave={() => setActive(null)}
              >
                <span className="p-source__edge" aria-hidden="true" />
                <span className="p-source__head">
                  <span className="p-source__n" aria-hidden="true">{n}</span>
                  <span className="p-source__name">{point.title}</span>
                </span>
                <span className="p-source__text">{point.evidence}</span>
              </div>
            )
          })}
        </aside>

        <Threads containerRef={benchRef} getPairs={getPairs} active={active} epoch={epoch} />
      </div>
    </section>
  )
}

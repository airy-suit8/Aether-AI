import { useEffect, useMemo, useRef, useState } from 'react'
import { Dialog } from '../../design/prism'
import type { PrismStyle } from '../../design/prism'
import { sourceHue } from '../../design/spectrum'
import { getDocumentFile, getPassage } from '../../services/api'
import type { PassageView, Source } from '../../services/api'
import { drawPage } from '../../services/pdf'
import type { DrawnPage } from '../../services/pdf'
import { piecesOfPassage } from './passageMatch'

interface SourceViewerProps {
  source: Source
  /** The source's number under its answer, for its hue */
  n: number
  onClose: () => void
}

const NOT_KEPT = 'This PDF was added before its pages were kept, so only its text is shown. Upload the same file again to see the page: nothing is read twice.'
const NOT_MARKED = 'The passage could not be marked on this page: its text is laid out differently there, or the page is an image.'

/**
 * SourceViewer — a source in its place. For a PDF whose file is kept, the cited page, drawn, with
 * the passage marked on it in the source's hue (kotaemon shows citations so); for any other
 * document, the passage among the ones either side of it.
 */
export default function SourceViewer({ source, n, onClose }: SourceViewerProps) {
  const documentId = source.document_id ?? 0
  const passage = source.passage ?? 0
  const [view, setView] = useState<PassageView | null>(null)
  const [file, setFile] = useState<ArrayBuffer | null>(null)
  const [drawn, setDrawn] = useState<DrawnPage | null>(null)
  const [problem, setProblem] = useState('')
  const frameRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const drawnWidth = useRef(0)
  const [redraw, setRedraw] = useState(0)

  const cited = view?.items.find((item) => item.passage === passage)
  const page = Number(cited?.page ?? source.page) || 1
  const showsPage = view?.kind === 'pdf' && view.original

  useEffect(() => {
    let cancelled = false
    const controller = new AbortController()
    getPassage(documentId, passage)
      .then(async (found) => {
        if (cancelled) return
        setView(found)
        if (found.kind === 'pdf' && found.original) {
          const bytes = await getDocumentFile(documentId, controller.signal)
          if (!cancelled) setFile(bytes)
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) setProblem(err instanceof Error ? err.message : 'The document could not be opened.')
      })
    return () => {
      cancelled = true
      controller.abort()
    }
  }, [documentId, passage])

  useEffect(() => {
    const canvas = canvasRef.current
    const frame = frameRef.current
    if (!file || !canvas || !frame) return undefined
    let cancelled = false
    drawnWidth.current = frame.clientWidth
    drawPage(file, page, canvas, frame.clientWidth)
      .then((result) => { if (!cancelled) setDrawn(result) })
      .catch(() => { if (!cancelled) setProblem('The page could not be drawn.') })
    return () => { cancelled = true }
  }, [file, page, redraw])

  // The page scales with the dialog; drawn again when the dialog grows much wider (a window
  // resized or a phone turned), so it stays sharp
  useEffect(() => {
    const frame = frameRef.current
    if (!frame) return undefined
    const observer = new ResizeObserver(() => {
      if (drawnWidth.current && frame.clientWidth > drawnWidth.current * 1.25) setRedraw((n) => n + 1)
    })
    observer.observe(frame)
    return () => observer.disconnect()
  }, [showsPage])

  // Each mark as a share of the page, so it stays on its words however wide the page is shown
  const marks = useMemo(() => {
    if (!drawn || !cited) return []
    const share = (part: number, whole: number) => `${(100 * part) / whole}%`
    return piecesOfPassage(drawn.texts.map((t) => t.text), cited.text).map((i) => {
      const t = drawn.texts[i]
      return { left: share(t.left, drawn.width), top: share(t.top, drawn.height), width: share(t.width, drawn.width), height: share(t.height, drawn.height) }
    })
  }, [drawn, cited])

  const openWhole = () => {
    if (!file) return
    const url = URL.createObjectURL(new Blob([file], { type: 'application/pdf' }))
    window.open(`${url}#page=${page}`, '_blank', 'noopener')
    setTimeout(() => URL.revokeObjectURL(url), 60_000)
  }

  const where = view && cited
    ? view.kind === 'pdf' ? `Page ${page}${drawn ? ` of ${drawn.pages}` : ''} · passage ${passage} of ${view.passages}` : `Passage ${passage} of ${view.passages}`
    : ''
  const style: PrismStyle = { '--hue': sourceHue(n) }

  return (
    <Dialog title={view?.filename ?? source.source} onClose={onClose} width="880px">
      <div className="x-viewer" style={style}>
        {where && <p className="x-viewer__where p-mono">{where}</p>}
        {problem && <p className="p-hint" role="alert">{problem}</p>}
        {!view && !problem && <p className="p-hint" role="status">Opening</p>}

        {showsPage && (
          <>
            <div className="x-viewer__page" ref={frameRef}>
              <canvas ref={canvasRef} role="img" aria-label={`Page ${page} of ${view.filename}`} />
              {marks.map((mark, i) => (
                <span
                  key={i}
                  className="x-viewer__mark"
                  aria-hidden="true"
                  style={mark}
                />
              ))}
            </div>
            <div className="x-viewer__foot">
              <p className="p-hint" role="status">
                {!drawn ? 'Drawing the page' : marks.length ? 'The cited passage is marked.' : NOT_MARKED}
              </p>
              <button type="button" className="p-btn" disabled={!file} onClick={openWhole}>Open the whole PDF</button>
            </div>
          </>
        )}

        {view && !showsPage && (
          <>
            {view.kind === 'pdf' && <p className="p-hint">{NOT_KEPT}</p>}
            <ol className="x-viewer__passages">
              {view.items.map((item) => (
                <li key={item.passage} data-cited={item.passage === passage || undefined}>
                  <span className="x-viewer__n p-mono">
                    {view.kind === 'pdf' ? `p. ${item.page} · ` : ''}passage {item.passage}
                  </span>
                  {item.passage === passage ? <mark>{item.text}</mark> : <p>{item.text}</p>}
                </li>
              ))}
            </ol>
          </>
        )}
      </div>
    </Dialog>
  )
}
